"""Create a new upload directory using an explicit allowlist; never copy the DB."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = ["README.md", "LICENSE", "DATA_SOURCES.md", "SECURITY.md", "pyproject.toml",
       "requirements.lock.txt", "alembic.ini", ".gitignore", ".dockerignore",
       ".env.example", "Dockerfile", "compose.yaml", "Start-GlycoAhead.cmd"]
DOCS = ["ARCHITECTURE.md", "MODEL_CARD.md", "TUNING.md", "FEATURE_EXPERIMENTS.md",
        "CONTEXT_INPUTS.md", "PORTFOLIO.md", "GITHUB_UPLOAD.md", "SUBMISSION_CHECKLIST.md",
        "submission.json"]
SCRIPTS = ["setup.ps1", "start.ps1", "export_github.py", "build_submission_pdfs.py"]


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def aggregate_metrics(metrics):
    return {key: value for key, value in metrics.items() if key != "patients"}


def package_release(destination):
    selected = destination / "release/selected_model"
    selected.mkdir(parents=True)
    ready = ROOT / "release/selected_model"
    if ready.is_dir():
        for name in ("model.joblib", "evaluation.json", "comparison.json", "manifest.json"):
            shutil.copy2(ready / name, selected / name)
        return
    active = json.loads((ROOT / "artifacts/active.json").read_text())["version"]
    source = ROOT / "artifacts" / active
    report = json.loads((source / "evaluation.json").read_text(encoding="utf-8"))
    if report.get("evaluation_scope") != "internal_robustness":
        raise ValueError("Activate the reviewed tuned model before exporting")
    shutil.copy2(source / "model.joblib", selected / "model.joblib")
    # Keep patient assignment IDs for the app, but omit individual observations,
    # per-patient outcomes and source-file audit listings.
    report.pop("provenance", None)
    for group in ("validation", "test"):
        report[group] = {key: aggregate_metrics(value) for key, value in report[group].items()}
    report["selected_validation"] = aggregate_metrics(report["selected_validation"])
    write(selected / "evaluation.json", report)
    experiments = ROOT / "artifacts/experiments"
    latest = json.loads((experiments / "latest.json").read_text())["run_id"]
    if Path(latest).name != latest or latest in (".", ".."):
        raise ValueError("Invalid latest comparison identifier")
    if json.loads((experiments / latest / "status.json").read_text())["state"] != "completed":
        raise ValueError("Latest comparison is incomplete")
    experiment = json.loads((experiments / latest / "report.json").read_text(encoding="utf-8"))
    comparison = {
        "aggregate_only": True,
        "protocol": {key: experiment["protocol"][key] for key in
                     ("run_id", "scope", "reference_version", "split_seeds", "horizon_minutes")},
        "summary": experiment["summary"],
        "recommended_settings": experiment["recommended_settings"],
        "runs": [{"seed": run["seed"], "models": {
            name: {key: (aggregate_metrics(value) if key in ("evaluation", "threshold_group") else value)
                   for key, value in result.items()
                   if key in ("evaluation", "threshold_group", "feature_count", "threshold", "selected_settings", "model_sha256")}
            for name, result in run["models"].items()}} for run in experiment["runs"]],
    }
    write(selected / "comparison.json", comparison)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["release_files"] = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(selected.iterdir())}
    write(selected / "manifest.json", manifest)


def export(destination):
    destination = destination.resolve()
    archive = destination.with_suffix(".zip")
    if destination.exists() or archive.exists():
        raise ValueError("Choose a new destination; existing directories or archives are never overwritten")
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("Export outside the original project")
    files = [ROOT / name for name in TOP]
    files += [ROOT / "docs" / name for name in DOCS]
    files += [ROOT / "docs/submission" / name for name in
              ("GlycoAhead-Architecture.pdf", "GlycoAhead-Presentation.pdf")]
    files += [ROOT / "scripts" / name for name in SCRIPTS]
    files += list((ROOT / "backend/glycoahead").glob("*.py"))
    files += list((ROOT / "backend/glycoahead/resources").glob("nutrition-*.json"))
    files += [p for p in (ROOT / "frontend/src").rglob("*") if p.is_file()]
    files += [p for p in (ROOT / "frontend/public").rglob("*") if p.is_file()]
    files += [ROOT / "frontend" / name for name in
              ("index.html", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts")]
    files += [p for p in (ROOT / "migrations").rglob("*")
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    files += list((ROOT / "tests").glob("*.py"))
    files += list((ROOT / ".github/workflows").glob("*.yml"))
    if any(not p.is_file() for p in files):
        raise ValueError("An allowlisted source file is missing")
    destination.mkdir(parents=True)
    for source in sorted(set(files)):
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    package_release(destination)
    hashes = {p.relative_to(destination).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in sorted(destination.rglob("*")) if p.is_file()}
    write(destination / "UPLOAD_MANIFEST.json",
          {"file_count_excluding_manifest": len(hashes), "sha256": hashes,
           "note": "Source and selected research model; patient database and raw recordings excluded."})
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(destination.parent))
    print(json.dumps({"folder": str(destination), "zip": str(archive),
                      "files": len(hashes) + 1, "zip_bytes": archive.stat().st_size}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    export(parser.parse_args().destination)
