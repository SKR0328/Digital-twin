# GitHub upload and local workflow

Use the separately exported `GlycoAhead-GitHub` folder. Its contents belong at the
repository root: README, backend, frontend, scripts, tests, migrations, docs,
release, project configuration, and `.github`. Do not upload the zip as your
repository's only file; extract it and upload the files inside.

## What is included

- FastAPI/Python backend, React/TypeScript frontend and database migrations.
- Existing tests, GitHub Actions workflow, pinned dependencies and Docker files.
- The selected calibrated model under `release/selected_model/`, with checksums.
- The existing v3 nutrition catalog, unchanged, plus its existing source metadata.
- Aggregate evaluation results and descriptions of the endpoint and limitations.
- No synthetic replacement. Researchers obtain the Shanghai release separately.

## What stays on your computer

- `data/`: the SQLite database, original records, local audit files and backups.
- `artifacts/`: all original models, cached training windows and per-patient
  experiment outputs. Only the selected model is copied into the release folder.
- `.venv/`, `node_modules/`, `frontend/dist/`, logs, `.env` and local Git history.
- Earlier food-inventory reports containing individual patient meal entries.

The nutrition references retain their original provenance and terms; the code's
MIT license does not relicense third-party data. See `DATA_SOURCES.md`.

## Upload with Git

From the **exported folder**, after creating an empty GitHub repository:

```powershell
git init
git add .
git status
git commit -m "Release GlycoAhead research application"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/glycoahead.git
git push -u origin main
```

Replace the URL with your repository's URL. No push or GitHub repository creation
was performed by this preparation step. Review the staged list before publishing.
Alternatively, upload the extracted contents through GitHub's upload interface,
including `.github`, `.gitignore` and `.env.example`.

## Recreate the upload folder

From the original prepared workspace:

```powershell
python scripts/export_github.py --destination ../GlycoAhead-GitHub-next
```

The destination must not exist. The exporter copies an explicit allowlist,
creates a SHA-256 manifest and a sibling zip. It does not alter the source data
or remove existing files. Exported folders can be exported again from their
packaged release without the original training archive.

## What changed on 20 October 2026

The reviewed seed-2026 tuning winner is active for **new** replay sessions:
learning rate 0.05, 140 iterations, 15 leaves, minimum 80 samples per leaf,
L2 regularization 10, fixed random seed 2026 and no early stopping.
Sigmoid calibration remains fitted on separate patients. The selected alert
threshold is 0.32, and the cooldown is still 75 minutes.

Existing replay sessions retain their original model. Start a new patient replay
or use the restart control to see the new model. Predictions already saved in the
database are not rewritten.

The current nutrition catalog and source files were not modified.


## Latest interface and comparison update

The upload package includes both newly tuned meal variants and their aggregate results. Model evidence shows four rows: tuned current, tuned meal timing, tuned pre-meal glucose and baseline. Earlier rows remain available in the full JSON report. The top-bar prototype wording and the separate limitations panel were removed; the model card retains the evaluation scope and limitations. The nutrition catalog and deployed current-model weights are unchanged by this update.
