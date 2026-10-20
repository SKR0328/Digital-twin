"""Versioned, calibrated probability models. Load only locally generated artifacts."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from .config import ARTIFACTS
from .domain import SCHEMA
from .context import CONTEXT_SCHEMA, CLEAN_CONTEXT_SCHEMA
from .nutrition import NUTRITION_SCHEMA, catalog_digest


@dataclass
class CalibratedModel:
    estimator: object
    columns: list[str]
    calibrator: object | None = None

    def raw(self, features: list[dict]) -> np.ndarray:
        x = np.array([[f.get(c) if f.get(c) is not None else np.nan for c in self.columns] for f in features], dtype=float)
        return self.estimator.predict_proba(x)[:, 1]

    def calibrate(self, features: list[dict], labels: np.ndarray, weights: np.ndarray):
        raw = np.clip(self.raw(features), 1e-6, 1-1e-6)
        logits = np.log(raw/(1-raw)).reshape(-1, 1)
        self.calibrator = LogisticRegression(C=1.0, max_iter=1000)
        self.calibrator.fit(logits, labels, sample_weight=weights)

    def predict(self, features: list[dict]) -> np.ndarray:
        raw = np.clip(self.raw(features), 1e-6, 1-1e-6)
        return self.calibrator.predict_proba(np.log(raw/(1-raw)).reshape(-1, 1))[:, 1] if self.calibrator else raw


@dataclass
class ModelBundle:
    version: str
    horizon: int
    threshold: float
    model: CalibratedModel
    metadata: dict
    personalization_enabled: bool = True


_cache: dict[str, ModelBundle] = {}


def load_bundle(path: str, expected_hash: str) -> ModelBundle:
    candidate = Path(path)
    candidate = (candidate if candidate.is_absolute() else ARTIFACTS / candidate).resolve()
    if not candidate.is_relative_to(ARTIFACTS.resolve()):
        raise ValueError("Artifact must be under the local artifacts directory")
    key = str(candidate) + expected_hash
    if key not in _cache:
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("Model artifact checksum mismatch")
        loaded = joblib.load(candidate)
        if not isinstance(loaded, ModelBundle) or loaded.metadata.get("schema") not in (SCHEMA, CONTEXT_SCHEMA, CLEAN_CONTEXT_SCHEMA, NUTRITION_SCHEMA):
            raise ValueError("Model feature schema is incompatible with this application")
        if loaded.metadata.get("schema") == NUTRITION_SCHEMA and catalog_digest(loaded.metadata["nutrition_catalog"]) != loaded.metadata["nutrition_catalog_id"]:
            raise ValueError("Nutrition catalog checksum mismatch")
        _cache[key] = loaded
    return _cache[key]


def active_version() -> str:
    path = ARTIFACTS / "active.json"
    if not path.exists():
        raise ValueError("No active model. Run the training command first.")
    return json.loads(path.read_text())["version"]


def activate_version(version_id: str, *, development_demo: bool = False):
    from .db import Session, ModelVersion, AuditEvent
    with Session.begin() as db:
        version = db.get(ModelVersion, version_id)
        if version is None:
            raise ValueError("Unknown model version")
        load_bundle(version.path, version.sha256)
        report_path = ARTIFACTS / version.id / "evaluation.json"
        if not report_path.is_file():
            raise ValueError("Model has no evaluation report")
        scope = json.loads(report_path.read_text(encoding="utf-8")).get("evaluation_scope", "held_out_test")
        if scope == "development_only" and not development_demo:
            raise ValueError("Development-only candidate: use --development-demo after reviewing validation results for local research replay")
        temporary = ARTIFACTS / "active.pending"
        temporary.write_text(json.dumps({"version": version_id, "evaluation_scope": scope, "development_demo": development_demo}), encoding="utf-8")
        temporary.replace(ARTIFACTS / "active.json")
        db.add(AuditEvent(kind="model_activated", entity_id=version_id, details={"sha256": version.sha256, "evaluation_scope": scope, "development_demo": development_demo}))
