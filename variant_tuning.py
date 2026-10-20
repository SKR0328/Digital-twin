"""Extend a frozen comparison with training-only searches for both meal variants."""
from datetime import datetime, timezone
from hashlib import sha256
import gzip
import json
from pathlib import Path
import shutil
import uuid

import joblib
import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss

from .config import ARTIFACTS
from .evaluation import choose_threshold
from .experiments import METRICS, report_for, summarize, write_json
from .ml import CalibratedModel
from .training import patient_weights
from .tuning import CANDIDATES, inner_folds, estimator, matrix

VARIANTS = ("plus_meal_timing", "plus_premeal_glucose")


def tune_meal_variants(experiment):
    if Path(experiment).name != experiment or experiment in (".", ".."):
        raise ValueError("Provide a local experiment identifier")
    parent = ARTIFACTS / "experiments" / experiment
    if json.loads((parent / "status.json").read_text())["state"] != "completed":
        raise ValueError("Parent experiment must be complete")
    report = json.loads((parent / "report.json").read_text())
    for run in report["runs"]:
        if "tuned_current" not in run["models"]:
            raise ValueError("Use the completed current-model tuning comparison")
        if any("tuned_" + name in run["models"] for name in VARIANTS):
            raise ValueError("These variants have already been tuned in this comparison")
    for name in ("training.py", "evaluation.py", "domain.py", "ml.py", "experiments.py"):
        if sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != report["protocol"]["source_sha256"][name]:
            raise ValueError(f"Frozen comparison code changed: {name}")
    archive = parent / "windows.joblib"
    if sha256(archive.read_bytes()).hexdigest() != report["coverage"]["windows_sha256"]:
        raise ValueError("Window checksum mismatch")
    for run in report["runs"]:
        for name, result in run["models"].items():
            path = parent / str(run["seed"]) / name / "model.joblib"
            if sha256(path.read_bytes()).hexdigest() != result["model_sha256"]:
                raise ValueError("Parent model checksum mismatch")
    active_before = (ARTIFACTS / "active.json").read_bytes()
    original_runs = json.loads(json.dumps(report["runs"]))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    root = parent.parent / run_id
    shutil.copytree(parent, root)
    (root / "report.json").unlink()
    if (root / "verification.json").exists():
        (root / "verification.json").unlink()
    protocol = report["protocol"]
    protocol.update(run_id=run_id, variant_tuning_parent=experiment,
                    variant_tuning_parent_report_sha256=sha256((parent / "report.json").read_bytes()).hexdigest())
    for variant in VARIANTS:
        protocol["features"]["tuned_" + variant] = protocol["features"][variant]
    protocol["variant_tuning"] = {
        "variants": list(VARIANTS), "candidates": CANDIDATES,
        "folds": {str(r["seed"]): inner_folds(r["patients"]["train"], r["seed"]) for r in report["runs"]},
        "selection": "Maximum mean inner-fold patient-weighted average precision; tie-break lower raw Brier, then fixed candidate order.",
        "scope": "Only the 60 training patients enter search, with 40 fit/20 inner validation per fold.",
        "budget": "2 variants x 3 outer splits x 8 candidates x 3 folds = 144 inner fits; 6 final fits.",
        "finalization": "Refit on 60; calibrate on 10; choose threshold on 10; evaluate on 20. Same original splits, labels, windows and cooldown.",
        "display": "Tuned variants replace corresponding untuned rows; original results remain in the archive.",
        "limitations": "Internal robustness on a previously inspected cohort. No adaptive expansion based on evaluation scores. Improvement is not guaranteed."
    }
    for name in ("variant_tuning.py", "tuning.py"):
        source = (Path(__file__).parent / name).read_bytes()
        (root / ("variant-search-" + name)).write_bytes(source)
        protocol["variant_tuning"][name + "_sha256"] = sha256(source).hexdigest()
    write_json(root / "protocol.json", protocol)
    write_json(root / "status.json", {"state": "loading_frozen_windows"})
    try:
        data = joblib.load(archive)
        rows, exposure = data["rows"], data["exposure"]
        horizon = protocol["horizon_minutes"]
        tuning_results = {}
        verified_predictions = True
        for run in report["runs"]:
            seed = run["seed"]
            subsets = {role: [r for r in rows if r["patient"] in ids] for role, ids in run["patients"].items()}
            if {role: len(v) for role, v in subsets.items()} != run["window_counts"]:
                raise ValueError("Split/window mismatch")
            groups = [set(ids) for ids in run["patients"].values()]
            if any(a & b for i, a in enumerate(groups) for b in groups[i + 1:]):
                raise ValueError("Outer patient groups overlap")
            folds = protocol["variant_tuning"]["folds"][str(seed)]
            if sorted(p for fold in folds for p in fold) != sorted(run["patients"]["train"]):
                raise ValueError("Inner folds do not partition training patients")
            tuning_results[str(seed)] = {}
            for variant in VARIANTS:
                name = "tuned_" + variant
                columns = protocol["features"][variant]
                fold_data = []
                for validation_ids in folds:
                    training = [r for r in subsets["train"] if r["patient"] not in validation_ids]
                    validation = [r for r in subsets["train"] if r["patient"] in validation_ids]
                    if any(len({r["label"] for r in part}) != 2 for part in (training, validation)):
                        raise ValueError("Inner fold lacks both labels")
                    fold_data.append((matrix(training, columns), np.array([r["label"] for r in training]), patient_weights(training),
                                      matrix(validation, columns), np.array([r["label"] for r in validation]), patient_weights(validation)))
                scores = []
                for settings in CANDIDATES:
                    ap, brier = [], []
                    for fold, (x, y, weights, vx, vy, vw) in enumerate(fold_data):
                        write_json(root / "status.json", {"state": "tuning", "seed": seed,
                                   "variant": variant, "candidate": settings["name"], "fold": fold + 1})
                        learner = estimator(settings)
                        learner.fit(x, y, model__sample_weight=weights)
                        probabilities = learner.predict_proba(vx)[:, 1]
                        ap.append(float(average_precision_score(vy, probabilities, sample_weight=vw)))
                        brier.append(float(brier_score_loss(vy, probabilities, sample_weight=vw)))
                    scores.append({"settings": settings, "fold_average_precision": ap, "fold_raw_brier": brier,
                                   "mean_average_precision": float(np.mean(ap)), "mean_raw_brier": float(np.mean(brier))})
                    write_json(root / f"variant-tuning-{seed}-{variant}-progress.json", scores)
                    print(json.dumps({"seed": seed, "variant": variant, "candidate": settings["name"],
                                      "inner_ap": scores[-1]["mean_average_precision"]}), flush=True)
                winner = max(scores, key=lambda s: (s["mean_average_precision"], -s["mean_raw_brier"]))
                tuning_results[str(seed)][variant] = {"winner": winner, "candidates": scores, "validation_patient_folds": folds}
                write_json(root / f"variant-tuning-{seed}-{variant}.json", tuning_results[str(seed)][variant])
                learner = estimator(winner["settings"])
                learner.fit(matrix(subsets["train"], columns), np.array([r["label"] for r in subsets["train"]]),
                            model__sample_weight=patient_weights(subsets["train"]))
                model = CalibratedModel(learner, columns)
                model.calibrate([r["features"] for r in subsets["calibration"]],
                                np.array([r["label"] for r in subsets["calibration"]]), patient_weights(subsets["calibration"]))
                threshold_rows = subsets["threshold"]
                tp = model.predict([r["features"] for r in threshold_rows])
                threshold, _ = choose_threshold(threshold_rows, tp, horizon, exposure)
                evaluation_rows = subsets["evaluation"]
                probabilities = model.predict([r["features"] for r in evaluation_rows])
                location = root / str(seed) / name
                location.mkdir()
                joblib.dump(model, location / "model.joblib")
                reloaded = joblib.load(location / "model.joblib")
                if not np.array_equal(probabilities, reloaded.predict([r["features"] for r in evaluation_rows])):
                    raise ValueError("Saved model predictions differ")
                result = {"feature_count": len(columns), "threshold": threshold, "selected_settings": winner["settings"],
                          "threshold_group": report_for(threshold_rows, tp, threshold, horizon, exposure),
                          "evaluation": report_for(evaluation_rows, probabilities, threshold, horizon, exposure),
                          "model_sha256": sha256((location / "model.joblib").read_bytes()).hexdigest()}
                write_json(location / "metrics.json", result)
                with gzip.open(location / "evaluation-predictions.jsonl.gz", "wt", encoding="utf-8") as output:
                    for row, probability in zip(evaluation_rows, probabilities):
                        output.write(json.dumps({k: row[k] for k in ("patient", "recording", "time", "label", "events")} |
                                                {"probability": float(probability)}) + "\n")
                run["models"][name] = result
                write_json(root / f"run-{seed}.json", run)
                print(json.dumps({"seed": seed, "variant": variant, "selected": winner["settings"]["name"],
                                  **{k: result["evaluation"][k] for k in METRICS}}), flush=True)
        report["variant_tuning_results"] = tuning_results
        report["summary"] = summarize(report["runs"])
        report["active_model_unchanged"] = (ARTIFACTS / "active.json").read_bytes() == active_before
        if not report["active_model_unchanged"]:
            raise RuntimeError("Active model changed during tuning")
        unchanged = all(new["models"][name] == result
                        for old, new in zip(original_runs, report["runs"]) for name, result in old["models"].items())
        if not unchanged:
            raise RuntimeError("An original result changed")
        write_json(root / "verification.json", {"original_results_unchanged": unchanged,
                   "outer_and_inner_patient_separation": True, "training_only_selection": True,
                   "saved_model_predictions_reproduce": verified_predictions, "active_unchanged": True})
        write_json(root / "report.json", report)
        write_json(root / "status.json", {"state": "completed", "new_inner_fits": 144, "new_final_fits": 6,
                                        "models_evaluated": sum(len(r["models"]) for r in report["runs"])})
        write_json(root.parent / "latest.json", {"run_id": run_id})
        print(f"Complete: {root / 'report.json'}", flush=True)
        return report
    except Exception as exc:
        write_json(root / "status.json", {"state": "failed", "error": str(exc)})
        raise
