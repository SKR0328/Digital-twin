"""Reproducible CPU training. The test patients never select models or thresholds."""
from datetime import datetime, timezone
from collections import defaultdict
import hashlib
import json
import platform
import uuid
import joblib
import numpy as np
import sklearn
from sqlalchemy import select
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from .db import Session, Recording, SourceReading, ModelVersion, AuditEvent, ContextEvent
from .context import context_features, CONTEXT_FEATURES, CONTEXT_SCHEMA, CLEAN_CONTEXT_SCHEMA
from .domain import make_features, onset_indices, minutes_between, FEATURES, SENSOR_FEATURES, HISTORY_FEATURES, BASELINE_FEATURES, SCHEMA
from .ml import CalibratedModel, ModelBundle
from .evaluation import sequential_probabilities, choose_threshold, full_report
from .config import ARTIFACTS
from .nutrition import latest_catalog, missing_meal, nutrition_features, NUTRITION_FEATURES, NUTRITION_SCHEMA


def build_windows(records: list, readings: dict, horizon: int, contexts=None, nutrition_catalog=None) -> tuple[list[dict], dict]:
    rows, exposure = [], {}
    for record in records:
        data = readings[record.id]
        onsets = onset_indices(data)
        exposure[record.id] = sum(min(15, max(0, minutes_between(b["time"], a["time"]))) for a,b in zip(data, data[1:]))/1440
        segment, segment_start = 0, data[0]["time"]
        steps = horizon//15
        for i, reading in enumerate(data):
            if i and minutes_between(reading["time"], data[i-1]["time"]) != 15:
                segment += 1
                segment_start = reading["time"]
            if i < 12 or i+steps+1 >= len(data):
                continue
            features, _ = make_features(data[i-12:i+1], record.profile)
            if features is None:
                continue
            if contexts is not None:
                available = [e for e in contexts[record.id] if not missing_meal(e)]
                features.update(context_features(available, reading["time"], segment_start))
                if nutrition_catalog:
                    features.update(nutrition_features(available, reading["time"], segment_start, nutrition_catalog))
            if any(minutes_between(data[j]["time"], data[j-1]["time"]) != 15 for j in range(i+1, i+steps+2)):
                continue
            events = [data[j]["time"] for j in onsets if i < j <= i+steps]
            rows.append({"patient": record.patient_id, "recording": record.id, "time": reading["time"], "features": features,
                         "label": int(bool(events)), "events": events, "segment": segment, "segment_start": segment_start})
    return rows, exposure


def patient_weights(rows):
    counts = defaultdict(int)
    for row in rows:
        counts[row["patient"]] += 1
    weights = np.array([1/counts[row["patient"]] for row in rows])
    return weights/weights.mean()


def fit_model(rows, cal_rows, columns, boosting=False):
    x = np.array([[r["features"].get(c) if r["features"].get(c) is not None else np.nan for c in columns] for r in rows])
    y = np.array([r["label"] for r in rows])
    estimator = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler()),
                          ("model", HistGradientBoostingClassifier(max_iter=140, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=10, early_stopping=False, random_state=2026) if boosting
                           else LogisticRegression(C=0.3, max_iter=1200, random_state=2026))])
    estimator.fit(x, y, model__sample_weight=patient_weights(rows))
    model = CalibratedModel(estimator, columns)
    model.calibrate([r["features"] for r in cal_rows], np.array([r["label"] for r in cal_rows]), patient_weights(cal_rows))
    return model


def train(horizon: int = 60, activate: bool = True, context: bool = False, development_only: bool = False, nutrition: bool = False) -> dict:
    context = context or nutrition
    catalog_id, catalog = None, None
    if development_only and activate:
        raise ValueError("Development-only candidates cannot be automatically activated")
    with Session() as session:
        if nutrition:
            catalog_id, catalog = latest_catalog(session)
        records = session.scalars(select(Recording).order_by(Recording.id)).all()
        if len({r.patient_id for r in records}) < 30:
            raise ValueError("Need at least 30 independent patients for this fixed training protocol")
        readings = defaultdict(list)
        for r in session.scalars(select(SourceReading).order_by(SourceReading.recording_id, SourceReading.position)):
            readings[r.recording_id].append({"time": r.time, "glucose": r.glucose})
        contexts = defaultdict(list) if context else None
        if context:
            if any(r.audit.get("context_schema") != CONTEXT_SCHEMA for r in records):
                raise ValueError("Re-run import-shanghai to import timestamped context for every recording")
            for e in session.scalars(select(ContextEvent).order_by(ContextEvent.recording_id, ContextEvent.time)):
                contexts[e.recording_id].append({"time": e.time, "kind": e.kind, "payload": e.payload})
    print("Building chronological windows...", flush=True)
    rows, exposure = build_windows(records, readings, horizon, contexts, catalog)
    columns = FEATURES + CONTEXT_FEATURES if context else FEATURES
    schema = CLEAN_CONTEXT_SCHEMA if context else SCHEMA
    if nutrition:
        columns = columns + NUTRITION_FEATURES
        schema = NUTRITION_SCHEMA
    patients = sorted({r.patient_id for r in records})
    np.random.default_rng(2026).shuffle(patients)
    n = len(patients)
    splits = {"train": patients[:int(n*.6)], "calibration": patients[int(n*.6):int(n*.7)],
              "validation": patients[int(n*.7):int(n*.8)], "test": patients[int(n*.8):]}
    subsets = {key: [r for r in rows if r["patient"] in ids] for key, ids in splits.items()}
    for key, subset in subsets.items():
        if len({r["label"] for r in subset}) < 2:
            raise ValueError(f"Split {key} does not contain both outcomes")
    specs = {"trend_baseline": (BASELINE_FEATURES, False), "history_only": (HISTORY_FEATURES, False),
             "sensor_only": (SENSOR_FEATURES, True), "combined": (FEATURES, True)}
    selected_name = "context_combined" if context else "combined"
    if context:
        specs[selected_name] = (FEATURES + CONTEXT_FEATURES, True)
    if nutrition:
        selected_name = "nutrition_combined"
        specs[selected_name] = (columns, True)
    models, validation = {}, {}
    val = subsets["validation"]
    for name, (columns, boosting) in specs.items():
        print(f"Training {name} ({horizon} minute horizon)...", flush=True)
        model = fit_model(subsets["train"], subsets["calibration"], columns, boosting)
        models[name] = model
        probabilities = model.predict([r["features"] for r in val])
        threshold, _ = choose_threshold(val, probabilities, horizon, exposure)
        validation[name] = full_report(val, probabilities, threshold, horizon, exposure)
    population = models[selected_name].predict([r["features"] for r in val])
    personal = sequential_probabilities(val, population, horizon)
    threshold = validation[selected_name]["threshold"]
    validation["personalized"] = full_report(val, personal, threshold, horizon, exposure)
    # Fixed threshold comparison; do not enable adaptation simply because it exists.
    vpop, vper = validation[selected_name], validation["personalized"]
    personal_enabled = (vper["brier"] <= vpop["brier"] and vper["event_recall"] >= vpop["event_recall"]-0.02
                        and vper["false_alerts_per_patient_day"] <= vpop["false_alerts_per_patient_day"])
    selected_validation = vper if personal_enabled else vpop
    print("Development-only: test metrics withheld." if development_only else "Evaluating reserved test patients; prior test results have already been inspected.", flush=True)
    test = subsets["test"]
    results = {}
    for name, model in ([] if development_only else models.items()):
        probabilities = model.predict([r["features"] for r in test])
        results[name] = full_report(test, probabilities, validation[name]["threshold"], horizon, exposure)
        if name == selected_name:
            results["personalized"] = full_report(test, sequential_probabilities(test, probabilities, horizon), threshold, horizon, exposure)
            # Feature noise scenario: retain original labels, perturb past glucose only.
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    report = {"version": version, "horizon_minutes": horizon, "feature_schema": schema, "seed": 2026,
              "evaluation_scope": "development_only" if development_only else "reserved_test_reused",
              "nutrition_catalog_id": catalog_id,
              "split_patients": splits, "counts": {k: len(v) for k,v in subsets.items()},
              "validation": validation, "test": results, "selected_model": selected_name, "personalization_enabled": personal_enabled,
              "threshold": threshold, "selected_validation": selected_validation,
              "proposed_targets": {"event_recall": 0.70, "false_alerts_per_patient_day": 1.0, "median_lead_minutes": horizon/2},
              "validation_targets_met": bool(selected_validation["event_recall"] >= .7 and selected_validation["false_alerts_per_patient_day"] <= 1 and (selected_validation["median_lead_minutes"] or 0) >= horizon/2),
              "protocol": {"split": "60/10/10/20 patients; all visits grouped; seed 2026", "calibration": "Sigmoid calibration on separate patients, equal patient total weight", "threshold": "Highest validation event recall at <=1 false alert per monitored patient-day; 75-minute cooldown for 60-minute horizon", "personalization": "Bounded log-odds offset; >=20 spaced matured labels and >=24h contiguous history; reset at gaps and visits", "denominator": "Events with eligible fully labelled windows; days sum observed inter-reading intervals capped at 15 minutes; coverage reported separately", "bootstrap": "500 patient-cluster resamples, percentile 95% intervals; no individual-window independence assumption"},
              "provenance": [{"recording": r.id, "source_sha256": r.source_sha256, "summary_sha256": r.summary_sha256} for r in records],
              "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__},
              "limitations": ["Research replay, not prospective clinical validation", "Chinese cohort; no Indian external validation", "Age and disease duration availability assumed at enrollment", "Meal and medication availability assumed at source-row time; administration/documentation time not independently verified", "Unrecorded meals or medicines are unknown, not absent", "Food mass is not carbohydrate content; medication entry features are not a pharmacological model", "Undated clinical summary fields displayed only", "No causal treatment model or medication recommendations", "Full noise/missingness robustness and clinical review remain outstanding", "Short recordings limit personalization; test outcomes may update state only after they mature"]}
    report["coverage"] = {"eligible_labelled_windows": len(rows), "source_readings": sum(len(v) for v in readings.values()), "note": "Suppression while above threshold, warm-up, gaps and incomplete future labels reduce coverage."}
    directory = ARTIFACTS / version
    directory.mkdir()
    bundle = ModelBundle(version, horizon, threshold, models[selected_name], {"features": columns, "schema": schema}, personal_enabled)
    if catalog:
        bundle.metadata.update(nutrition_catalog_id=catalog_id, nutrition_catalog=catalog)
        report["nutrition_assumptions"] = catalog["assumptions"]
        report["nutrition_source"] = catalog["source"]
    model_path = directory / "model.joblib"
    joblib.dump(bundle, model_path)
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    (directory / "evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps({"version": version, "sha256": digest, "feature_schema": schema, "horizon": horizon, "threshold": threshold}, indent=2))
    with Session.begin() as session:
        session.add(ModelVersion(id=version, path=f"{version}/model.joblib", sha256=digest, info={"horizon": horizon, "threshold": threshold, "personalization_enabled": personal_enabled}))
        session.add(AuditEvent(kind="model_trained", entity_id=version, details={"sha256": digest, "validation_targets_met": report["validation_targets_met"]}))
    if activate:
        temporary = ARTIFACTS / "active.pending"
        temporary.write_text(json.dumps({"version": version}), encoding="utf-8")
        temporary.replace(ARTIFACTS / "active.json")
    print(json.dumps({"version": version, "test": {k: {metric: v[metric] for metric in ("event_recall", "false_alerts_per_patient_day", "median_lead_minutes", "brier")} for k,v in results.items()}, "personalization_enabled": personal_enabled}, indent=2), flush=True)
    return report
