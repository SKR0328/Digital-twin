"""Event-level reporting and sequential personalization with matured outcomes only."""
from collections import defaultdict
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
from .domain import TwinState, minutes_between


def sequential_probabilities(rows: list[dict], population: np.ndarray, horizon: int) -> np.ndarray:
    output = np.zeros(len(rows))
    by_record = defaultdict(list)
    for i, row in enumerate(rows):
        by_record[row["recording"]].append(i)
    for indices in by_record.values():
        state = TwinState()
        pending = []
        segment = None
        for i in indices:
            row = rows[i]
            if row["segment"] != segment:
                state = TwinState(segment_start=row["segment_start"])
                pending = []
                segment = row["segment"]
            while pending and minutes_between(row["time"], rows[pending[0]]["time"]) >= horizon+15:
                old = pending.pop(0)
                state.learn(float(population[old]), rows[old]["label"], rows[old]["time"], horizon)
            output[i] = state.personalize(float(population[i]), row["time"])
            pending.append(i)
    return output


def alert_metrics(rows: list[dict], probabilities: np.ndarray, threshold: float, horizon: int, exposure: dict) -> dict:
    events = defaultdict(set)
    patient_data = defaultdict(lambda: {"events": 0, "caught": 0, "false_alerts": 0, "alerts": 0, "leads": [], "days": 0.0})
    for row in rows:
        events[row["recording"]].update(row["events"])
    record_patient = {row["recording"]: row["patient"] for row in rows}
    for record, patient in record_patient.items():
        patient_data[patient]["events"] += len(events[record])
        patient_data[patient]["days"] += exposure.get(record, 0)
    last_alert = {}
    caught = defaultdict(set)
    for row, probability in zip(rows, probabilities):
        record = row["recording"]
        if probability < threshold or (record in last_alert and minutes_between(row["time"], last_alert[record]) < horizon+15):
            continue
        last_alert[record] = row["time"]
        stats = patient_data[row["patient"]]
        stats["alerts"] += 1
        matched = sorted(e for e in row["events"] if e not in caught[record])
        if matched:
            event = matched[0]
            caught[record].add(event)
            stats["caught"] += 1
            stats["leads"].append(minutes_between(event, row["time"]))
        else:
            stats["false_alerts"] += 1
    totals = {key: sum(p[key] for p in patient_data.values()) for key in ("events", "caught", "false_alerts", "alerts", "days")}
    leads = [lead for p in patient_data.values() for lead in p["leads"]]
    return {"event_recall": totals["caught"]/totals["events"] if totals["events"] else None,
            "false_alerts_per_patient_day": totals["false_alerts"]/totals["days"] if totals["days"] else None,
            "median_lead_minutes": float(np.median(leads)) if leads else None,
            "event_count": totals["events"], "caught_events": totals["caught"], "alerts": totals["alerts"],
            "false_alerts": totals["false_alerts"], "monitored_days": totals["days"], "patients": dict(patient_data)}


def choose_threshold(rows, probabilities, horizon, exposure) -> tuple[float, dict]:
    candidates = []
    for threshold in np.linspace(0.02, 0.98, 49):
        report = alert_metrics(rows, probabilities, float(threshold), horizon, exposure)
        candidates.append((float(threshold), report))
    feasible = [(t, r) for t, r in candidates if (r["false_alerts_per_patient_day"] or 0) <= 1.0]
    return max(feasible or candidates, key=lambda item: (item[1]["event_recall"] or 0, -(item[1]["false_alerts_per_patient_day"] or 0), item[0]))


def full_report(rows, probabilities, threshold, horizon, exposure) -> dict:
    labels = np.array([r["label"] for r in rows])
    result = alert_metrics(rows, probabilities, threshold, horizon, exposure)
    result.update(threshold=threshold, windows=len(rows), positive_windows=int(labels.sum()),
                  brier=float(brier_score_loss(labels, probabilities)),
                  average_precision=float(average_precision_score(labels, probabilities)) if labels.any() else None,
                  roc_auc=float(roc_auc_score(labels, probabilities)) if len(set(labels)) == 2 else None)
    bins = []
    for lo in np.linspace(0, 0.9, 10):
        mask = (probabilities >= lo) & (probabilities < lo+0.1+1e-10)
        if mask.any():
            bins.append({"mean_probability": float(probabilities[mask].mean()), "observed_frequency": float(labels[mask].mean()), "count": int(mask.sum())})
    result["calibration_bins"] = bins
    # Cluster bootstrap: resample whole patients, not overlapping windows.
    groups = list(result["patients"].values())
    rng = np.random.default_rng(2026)
    recall, false_rates = [], []
    for _ in range(500):
        selected = [groups[i] for i in rng.integers(0, len(groups), len(groups))]
        events = sum(p["events"] for p in selected)
        days = sum(p["days"] for p in selected)
        if events:
            recall.append(sum(p["caught"] for p in selected)/events)
        if days:
            false_rates.append(sum(p["false_alerts"] for p in selected)/days)
    result["patient_bootstrap_95ci"] = {"event_recall": np.quantile(recall, [0.025, 0.975]).tolist() if recall else None,
                                        "false_alerts_per_patient_day": np.quantile(false_rates, [0.025, 0.975]).tolist() if false_rates else None}
    return result

