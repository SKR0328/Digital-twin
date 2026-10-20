"""Transactional replay: each source reading becomes observable exactly once."""
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from .db import Recording, SourceReading, ObservedReading, Replay, Prediction, Alert, AuditEvent, ModelVersion, ContextEvent, utcnow
from .context import context_features, CONTEXT_SCHEMA, CLEAN_CONTEXT_SCHEMA
from .domain import TwinState, make_features, minutes_between, add_minutes, resolve_outcome, onset_indices
from .ml import load_bundle, active_version
from .nutrition import NUTRITION_SCHEMA, nutrition_features, missing_meal, estimate_meal, latest_catalog


class DomainError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


def get_replay(db: DBSession, replay_id: str) -> Replay:
    replay = db.get(Replay, replay_id)
    if replay is None:
        raise DomainError(404, "Replay not found")
    return replay


def bundle_for(db, replay):
    version = db.get(ModelVersion, replay.model_id)
    return load_bundle(version.path, version.sha256)


def available_context(db, record_id, at, since):
    if not at or not since:
        return []
    start = max(since, add_minutes(at, -360))
    return [{"id": e.id, "time": e.time, "kind": e.kind, "payload": e.payload} for e in db.scalars(
        select(ContextEvent).where(ContextEvent.recording_id == record_id, ContextEvent.time >= start,
                                   ContextEvent.time <= at).order_by(ContextEvent.time, ContextEvent.id))]


def create_replay(db, recording_id: str) -> Replay:
    record = db.get(Recording, recording_id)
    if not record:
        raise DomainError(404, "Recording not found")
    model_id = active_version()
    if db.get(ModelVersion, model_id) is None:
        raise DomainError(503, "Active model is not registered")
    replay = Replay(id=uuid.uuid4().hex, recording_id=recording_id, model_id=model_id, state=TwinState().dump())
    db.add(replay)
    db.add(AuditEvent(kind="replay_created", entity_id=replay.id, details={"recording": recording_id, "model": model_id}))
    db.flush()
    return replay


def advance(db, replay_id: str, steps: int, expected_cursor: int):
    replay = get_replay(db, replay_id)
    if replay.cursor != expected_cursor:
        raise DomainError(409, "Replay moved since this request. Refresh before advancing again.")
    record = db.get(Recording, replay.recording_id)
    bundle = bundle_for(db, replay)
    incoming = db.scalars(select(SourceReading).where(SourceReading.recording_id == replay.recording_id,
                          SourceReading.position >= replay.cursor).order_by(SourceReading.position).limit(steps)).all()
    observed = [{"time": r.time, "glucose": r.glucose} for r in db.scalars(select(ObservedReading).where(ObservedReading.replay_id == replay_id).order_by(ObservedReading.time.desc()).limit(32)).all()][::-1]
    pending = db.scalars(select(Prediction).where(Prediction.replay_id == replay_id, Prediction.outcome_status == "pending").order_by(Prediction.time)).all()
    state = TwinState(**replay.state)
    last_alert = db.scalar(select(Alert).where(Alert.replay_id == replay_id).order_by(Alert.time.desc()).limit(1))
    last_alert_time = last_alert.time if last_alert else None
    for source in incoming:
        reading = {"time": source.time, "glucose": source.glucose}
        if observed and minutes_between(source.time, observed[-1]["time"]) != 15:
            state = TwinState(segment_start=source.time, revision=state.revision+1)
            for prediction in pending:
                prediction.outcome_status = "censored_gap"
            pending = []
            db.add(AuditEvent(kind="gap_state_reset", entity_id=replay_id, details={"event_time": source.time}))
        if state.segment_start is None:
            state.segment_start = source.time
        db.add(ObservedReading(replay_id=replay_id, **reading))
        observed.append(reading)
        observed = observed[-32:]
        for prediction in list(pending):
            if source.time < prediction.due_at:
                continue
            label = resolve_outcome(observed, prediction.time, bundle.horizon)
            prediction.outcome = label
            prediction.outcome_status = "resolved" if label is not None else "censored_gap"
            if label is not None:
                prediction.updated_state = int(state.learn(prediction.population_probability, label, prediction.time, bundle.horizon))
                prediction.state_after = state.dump()
            pending.remove(prediction)
        features, status = make_features(observed, record.profile)
        if features:
            context = available_context(db, record.id, source.time, state.segment_start)
            if bundle.metadata.get("schema") in (CONTEXT_SCHEMA, CLEAN_CONTEXT_SCHEMA, NUTRITION_SCHEMA):
                if bundle.metadata.get("schema") in (CLEAN_CONTEXT_SCHEMA, NUTRITION_SCHEMA):
                    context = [e for e in context if not missing_meal(e)]
                features.update(context_features(context, source.time, state.segment_start))
                features["context_event_ids"] = [e["id"] for e in context]
                if bundle.metadata.get("schema") == NUTRITION_SCHEMA:
                    features.update(nutrition_features(context, source.time, state.segment_start, bundle.metadata["nutrition_catalog"]))
                    features["nutrition_catalog_id"] = bundle.metadata["nutrition_catalog_id"]
            population = float(bundle.model.predict([features])[0])
            personal = state.personalize(population, source.time)
            prediction = Prediction(replay_id=replay_id, model_id=bundle.version, time=source.time,
                                    due_at=add_minutes(source.time, bundle.horizon+15), population_probability=population,
                                    personal_probability=personal, features=features, state_before=state.dump())
            db.add(prediction)
            db.flush()
            pending.append(prediction)
            deployed_probability = personal if bundle.personalization_enabled else population
            if deployed_probability >= bundle.threshold and (last_alert_time is None or minutes_between(source.time, last_alert_time) >= bundle.horizon+15):
                db.add(Alert(prediction_id=prediction.id, replay_id=replay_id, time=source.time, probability=deployed_probability))
                last_alert_time = source.time
        replay.cursor = source.position+1
        replay.virtual_time = source.time
    replay.state = state.dump()
    replay.updated_at = utcnow()
    if replay.cursor == record.count:
        for prediction in pending:
            prediction.outcome_status = "censored_record_end"
    db.flush()
    return replay


def snapshot(db, replay_id: str) -> dict:
    replay = get_replay(db, replay_id)
    record = db.get(Recording, replay.recording_id)
    bundle = bundle_for(db, replay)
    readings = [{"time": r.time, "glucose": r.glucose} for r in db.scalars(select(ObservedReading).where(ObservedReading.replay_id == replay_id).order_by(ObservedReading.time.desc()).limit(192)).all()][::-1]
    features, status = make_features(readings, record.profile)
    stale = bool(readings and replay.virtual_time and minutes_between(replay.virtual_time, readings[-1]["time"]) > 30)
    if stale:
        status = "stale"
    predictions = db.scalars(select(Prediction).where(Prediction.replay_id == replay_id).order_by(Prediction.time.desc()).limit(192)).all()[::-1]
    alerts = db.scalars(select(Alert).where(Alert.replay_id == replay_id).order_by(Alert.id.desc()).limit(40)).all()
    state = TwinState(**replay.state)
    context = available_context(db, record.id, readings[-1]["time"] if readings else None, state.segment_start)
    nutrition_view = None
    try:
        catalog_id, catalog = (bundle.metadata["nutrition_catalog_id"], bundle.metadata["nutrition_catalog"]) if bundle.metadata.get("schema") == NUTRITION_SCHEMA else latest_catalog(db)
        meals = [e for e in context if e["kind"] == "meal" and not missing_meal(e)]
        if meals:
            meal = meals[-1]
            nutrition_view = {"time": meal["time"], "catalog_id": catalog_id, "used_for_prediction": bundle.metadata.get("schema") == NUTRITION_SCHEMA,
                              **estimate_meal(meal["payload"], catalog)}
    except ValueError:
        pass  # A nutrition reference is optional for legacy CGM-only replays.
    latest = predictions[-1] if predictions else None
    latest_current = latest is not None and readings and latest.time == readings[-1]["time"] and status == "ready"
    return {"id": replay.id, "recording_id": record.id, "patient_id": record.patient_id, "profile": record.profile,
            "mode": "recorded_replay", "cursor": replay.cursor, "total": record.count, "complete": replay.cursor == record.count,
            "virtual_time": replay.virtual_time, "status": status, "readings": readings,
            "current_glucose": readings[-1]["glucose"] if readings else None,
            "trend": features["slope_15"] if features else None,
            "state": {**state.dump(), "ready": bool(replay.virtual_time and state.ready(replay.virtual_time)), "enabled_for_alerts": bundle.personalization_enabled},
            "model": {"version": bundle.version, "horizon": bundle.horizon, "threshold": bundle.threshold},
            "context_events": [e for e in context if not missing_meal(e)],
            "context_used_for_prediction": bundle.metadata.get("schema") in (CONTEXT_SCHEMA, CLEAN_CONTEXT_SCHEMA, NUTRITION_SCHEMA),
            "nutrition": nutrition_view,
            "current_prediction": prediction_dict(latest) if latest_current else None,
            "predictions": [prediction_dict(p) for p in predictions],
            "confirmed_events": [{"time": readings[i]["time"], "glucose": readings[i]["glucose"]} for i in onset_indices(readings)],
            "alerts": [{"id": a.id, "time": a.time, "probability": a.probability, "status": a.status, "acknowledged_at": a.acknowledged_at} for a in alerts],
            "source": {"dataset": "ShanghaiT2DM v5", "sha256": record.source_sha256, "summary_sha256": record.summary_sha256, "timezone": "Asia/Shanghai (assumed)", "audit": record.audit},
            "notice": "Research replay. A sensor-defined episode forecast is not a diagnosis or medication recommendation."}


def prediction_dict(prediction):
    return {"id": prediction.id, "time": prediction.time, "population": prediction.population_probability,
            "personalized": prediction.personal_probability, "outcome": prediction.outcome,
            "outcome_status": prediction.outcome_status, "due_at": prediction.due_at, "state_revision": prediction.state_before["revision"]}
