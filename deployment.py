"""Register a reviewed model without refitting or selecting on evaluation scores."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import joblib
from .config import ARTIFACTS
from .db import Session, ModelVersion, AuditEvent, initialize
from .ml import CalibratedModel, ModelBundle, load_bundle, activate_version
from .nutrition import catalog_digest, import_catalog


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def register(directory: Path):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    bundle = load_bundle(str(directory / "model.joblib"), manifest["sha256"])
    if bundle.version != directory.name or manifest["version"] != bundle.version:
        raise ValueError("Model version and directory disagree")
    report = json.loads((directory / "evaluation.json").read_text(encoding="utf-8"))
    if report["version"] != bundle.version or report["threshold"] != bundle.threshold:
        raise ValueError("Model and evaluation report disagree")
    with Session.begin() as db:
        existing = db.get(ModelVersion, bundle.version)
        if existing and existing.sha256 != manifest["sha256"]:
            raise ValueError("A different artifact already uses this version")
        if not existing:
            db.add(ModelVersion(id=bundle.version, path=f"{bundle.version}/model.joblib",
                                sha256=manifest["sha256"],
                                info={"horizon": bundle.horizon, "threshold": bundle.threshold,
                                      "personalization_enabled": bundle.personalization_enabled,
                                      "source": "reviewed_training_only_tuning"}))
            db.add(AuditEvent(kind="model_registered", entity_id=bundle.version,
                              details={"sha256": manifest["sha256"]}))
    return bundle


def promote_tuned(experiment: str):
    """The original deployment cohort is seed 2026; never choose the best outer run."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", experiment):
        raise ValueError("Invalid experiment identifier")
    root = ARTIFACTS / "experiments" / experiment
    if json.loads((root / "status.json").read_text())["state"] != "completed":
        raise ValueError("Experiment is incomplete")
    verified = json.loads((root / "verification.json").read_text())
    if not verified or not all(value is True for value in verified.values()):
        raise ValueError("Review the failed experiment integrity checks first")
    experiment_report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    protocol = experiment_report["protocol"]
    run = next(r for r in experiment_report["runs"] if r["seed"] == 2026)
    result = run["models"]["tuned_current"]
    model_path = root / "2026" / "tuned_current" / "model.joblib"
    if sha256(model_path.read_bytes()).hexdigest() != result["model_sha256"]:
        raise ValueError("Tuned artifact checksum mismatch")
    if result["selected_settings"] != experiment_report["tuning_results"]["2026"]["winner"]["settings"]:
        raise ValueError("Model does not match the training-only winner")
    with Session() as db:
        reference = db.get(ModelVersion, protocol["reference_version"])
        if reference is None or reference.sha256 != protocol["reference_model_sha256"]:
            raise ValueError("Reference model does not match the frozen protocol")
        old = load_bundle(reference.path, reference.sha256)
    if catalog_digest(old.metadata["nutrition_catalog"]) != protocol["nutrition_catalog_id"]:
        raise ValueError("Frozen nutrition catalog mismatch")
    model = joblib.load(model_path)  # trusted local output, checked above
    if not isinstance(model, CalibratedModel) or model.columns != old.metadata["features"]:
        raise ValueError("Tuned model features are incompatible with replay")
    version = f"tuned-{experiment}-seed2026"
    destination = ARTIFACTS / version
    if not destination.exists():
        old_report = json.loads((ARTIFACTS / old.version / "evaluation.json").read_text(encoding="utf-8"))
        report = deepcopy(old_report)
        splits = {("validation" if k == "threshold" else "test" if k == "evaluation" else k): v
                  for k, v in run["patients"].items()}
        validation = result["threshold_group"]
        report.update(version=version, evaluation_scope="internal_robustness", seed=2026,
                      split_patients=splits,
                      counts={("validation" if k == "threshold" else "test" if k == "evaluation" else k): v
                              for k, v in run["window_counts"].items()},
                      validation={"nutrition_combined": validation},
                      test={"nutrition_combined": result["evaluation"]},
                      selected_model="nutrition_combined", selected_validation=validation,
                      threshold=result["threshold"], personalization_enabled=False,
                      selected_settings=result["selected_settings"],
                      experiment_id=experiment,
                      validation_targets_met=bool(validation["event_recall"] >= .7
                                                 and validation["false_alerts_per_patient_day"] <= 1
                                                 and (validation["median_lead_minutes"] or 0) >= 30))
        report["protocol"]["tuning"] = protocol["tuning"]["selection"]
        report["protocol"]["personalization"] = "Disabled for this tuned release; benefit has not been established for these weights."
        report["limitations"] += [
            "Previously inspected cohort: internal robustness evidence, not fresh external validation.",
            "80.60% is the mean across three independently tuned runs, not this model's event recall.",
            "The seed-2026 model has 82.65% evaluation recall and 1.39 false alerts/day; it misses the proposed <=1/day target.",
        ]
        metadata = deepcopy(old.metadata)
        metadata.update(selected_settings=result["selected_settings"], experiment_id=experiment,
                        source_model_sha256=result["model_sha256"])
        bundle = ModelBundle(version, 60, result["threshold"], model, metadata, False)
        destination.mkdir()
        joblib.dump(bundle, destination / "model.joblib")
        write_json(destination / "evaluation.json", report)
        write_json(destination / "manifest.json",
                   {"version": version, "sha256": sha256((destination / "model.joblib").read_bytes()).hexdigest(),
                    "feature_schema": metadata["schema"], "horizon": 60, "threshold": bundle.threshold})
    register(destination)
    activate_version(version)
    return {"version": version, "threshold": result["threshold"], "settings": result["selected_settings"],
            "note": "New replays use this model; existing replays remain pinned."}


def install_release(source: Path):
    """Install a trusted bundled release; checksums detect corruption, not malicious pickle."""
    source = source.resolve()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", version):
        raise ValueError("Invalid model version")
    names = {"model.joblib", "evaluation.json", "manifest.json"}
    hashes = manifest.get("release_files")
    if not hashes or not {"model.joblib", "evaluation.json"} <= hashes.keys():
        raise ValueError("Release lacks checksums")
    if set(hashes) - {"model.joblib", "evaluation.json", "comparison.json"}:
        raise ValueError("Unexpected release file")
    for name, digest in hashes.items():
        if sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Release checksum mismatch: {name}")
    if hashes["model.joblib"] != manifest["sha256"]:
        raise ValueError("Release and model checksums disagree")
    initialize()
    destination = ARTIFACTS / version
    destination.mkdir(exist_ok=True)
    for name in names:
        target = destination / name
        if target.exists() and target.read_bytes() != (source / name).read_bytes():
            raise ValueError(f"Existing version differs: {name}")
    for name in names:
        shutil.copyfile(source / name, destination / name)
    bundle = register(destination)
    catalog_file = destination / "nutrition-catalog.json"
    write_json(catalog_file, bundle.metadata["nutrition_catalog"])
    import_catalog(catalog_file)
    # This is a display-only aggregate report, not a resumable training archive.
    if "comparison.json" in hashes:
        comparison = json.loads((source / "comparison.json").read_text(encoding="utf-8"))
        comparison_id = "packaged-" + version
        comparison_root = ARTIFACTS / "experiments" / comparison_id
        comparison_root.mkdir(parents=True, exist_ok=True)
        write_json(comparison_root / "report.json", comparison)
        write_json(comparison_root / "status.json", {"state": "completed", "aggregate_only": True})
        write_json(comparison_root.parent / "latest.json", {"run_id": comparison_id})
    activate_version(bundle.version)
    return {"version": bundle.version, "threshold": bundle.threshold}
