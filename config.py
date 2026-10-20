import os
from pathlib import Path

ROOT = Path(os.environ.get("GLYCOAHEAD_HOME", Path(__file__).resolve().parents[2])).resolve()
DATA = ROOT / "data"
ARTIFACTS = ROOT / "artifacts"
LOGS = ROOT / "logs"
for directory in (DATA, ARTIFACTS, LOGS):
    directory.mkdir(parents=True, exist_ok=True)
DATABASE_URL = "sqlite:///" + (DATA / "glycoahead.sqlite").as_posix()

