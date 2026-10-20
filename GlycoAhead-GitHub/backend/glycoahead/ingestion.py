"""Read-only import of originals; hashes make repeat imports idempotent."""
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sqlalchemy import select
from .db import Session, Patient, Recording, SourceReading, AuditEvent, ContextEvent
from .context import extract_events, text, CONTEXT_SCHEMA

SOURCE_URL = "https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933/5"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value):
    parsed = pd.to_numeric(value, errors="coerce")
    return float(parsed) if pd.notna(parsed) and np.isfinite(parsed) else None


def import_shanghai(folder: Path, summary_path: Path | None = None) -> dict:
    folder = folder.resolve()
    summary_path = summary_path.resolve() if summary_path else folder / "Shanghai_T2DM_Summary.xlsx"
    summary = pd.read_excel(summary_path)
    summary.columns = summary.columns.str.strip()
    if summary["Patient Number"].duplicated().any():
        raise ValueError("Duplicate clinical-summary recording IDs")
    summaries = summary.set_index("Patient Number")
    summary_hash = sha256(summary_path)
    imported = skipped = total = context_total = 0
    paths = sorted(p for p in (folder / "Shanghai_T2DM").glob("*") if p.suffix.lower() in (".xls", ".xlsx") and not p.name.startswith("~$"))
    if not paths:
        raise ValueError("No Shanghai_T2DM Excel recordings found")
    for path in paths:
        rid = path.stem
        if rid not in summaries.index:
            raise ValueError(f"No matching clinical summary: {rid}")
        source_hash = sha256(path)
        with Session.begin() as session:
            old = session.get(Recording, rid)
            if old:
                if old.source_sha256 != source_hash or old.summary_sha256 != summary_hash:
                    raise ValueError(f"Source changed for {rid}; use a new database/version")
                if old.audit.get("context_schema") == CONTEXT_SCHEMA:
                    skipped += 1
                    continue
            frame = pd.read_excel(path)
            frame.columns = frame.columns.astype(str).str.strip()
            events = extract_events(frame)
            row = summaries.loc[rid]
            clinical_context = {"availability": "undated; display only, excluded from prediction",
                "sex_code": number(row["Gender (Female=1, Male=2)"]), "bmi": number(row["BMI (kg/m2)"]),
                "smoking_pack_years": number(row["Smoking History (pack year)"]),
                "alcohol_history": text(row["Alcohol Drinking History (drinker/non-drinker)"]),
                "comorbidities": text(row["Comorbidities"]),
                "microvascular_complications": text(row["Diabetic Microvascular Complications"]),
                "macrovascular_complications": text(row["Diabetic Macrovascular  Complications"]),
                "summary_regimen": text(row["Hypoglycemic Agents"])}
            if old:
                old.profile = {**old.profile, "clinical_context": clinical_context,
                    "excluded": ["Undated laboratory measurements", "Undated clinical context", "Hypoglycemia outcome summary"]}
                old.audit = {**old.audit, "context_schema": CONTEXT_SCHEMA, "context_entries": len(events)}
                session.bulk_insert_mappings(ContextEvent, [{"recording_id": rid, **e} for e in events])
                session.add(AuditEvent(kind="context_imported", entity_id=rid, details={"entries": len(events), "schema": CONTEXT_SCHEMA, "sha256": source_hash}))
                context_total += len(events)
                skipped += 1
                continue
            glucose_column = next(c for c in frame.columns if c.startswith("CGM"))
            cleaned = pd.DataFrame({"time": pd.to_datetime(frame["Date"], errors="coerce"),
                                    "glucose": pd.to_numeric(frame[glucose_column], errors="coerce")})
            invalid = cleaned.time.isna() | cleaned.glucose.isna() | ~cleaned.glucose.between(20, 600)
            cleaned = cleaned.loc[~invalid].copy()
            conflicting = cleaned.groupby("time").glucose.nunique()
            conflicts = conflicting[conflicting > 1].index
            cleaned = cleaned.loc[~cleaned.time.isin(conflicts)].drop_duplicates("time").sort_values("time")
            if cleaned.empty:
                raise ValueError(f"No valid observations: {rid}")
            times = cleaned.time.dt.tz_localize("Asia/Shanghai").map(lambda t: t.isoformat()).tolist()
            patient_id = rid.split("_")[0]
            if session.get(Patient, patient_id) is None:
                session.add(Patient(id=patient_id))
                session.flush()
            profile = {"age": number(row["Age (years)"]), "diabetes_years": number(row["Duration of diabetes (years)"]),
                       "clinical_context": clinical_context,
                       "condition": "Type 2 diabetes", "history_assumption": "Age and duration treated as enrollment history; exact availability unverified.",
                       "excluded": ["Undated laboratory measurements", "Undated clinical context", "Hypoglycemia outcome summary"]}
            audit = {"raw_rows": len(frame), "excluded_rows": int(invalid.sum()), "conflicting_times": len(conflicts),
                     "gaps": int((cleaned.time.diff().dropna().dt.total_seconds() != 900).sum()), "timezone_assumption": "Asia/Shanghai",
                     "context_schema": CONTEXT_SCHEMA, "context_entries": len(events)}
            session.add(Recording(id=rid, patient_id=patient_id, profile=profile, source_sha256=source_hash,
                                  summary_sha256=summary_hash, source_name=path.name, start_time=times[0], end_time=times[-1], count=len(times), audit=audit))
            session.flush()
            session.bulk_insert_mappings(ContextEvent, [{"recording_id": rid, **e} for e in events])
            context_total += len(events)
            session.bulk_insert_mappings(SourceReading, [{"recording_id": rid, "position": i, "time": t, "glucose": float(g)} for i,(t,g) in enumerate(zip(times, cleaned.glucose))])
            session.add(AuditEvent(kind="recording_imported", entity_id=rid, details={"sha256": source_hash, "count": len(times), "source": SOURCE_URL}))
            imported += 1
            total += len(times)
    return {"imported_recordings": imported, "skipped_recordings": skipped, "new_readings": total, "new_context_entries": context_total}
