"""Recorded context, not inferred nutrition or pharmacological effects.

Event time is assumed to be availability time for this research replay. Originals
do not prove that entries were documented prospectively. Missing entries are unknown.
"""
import re
import pandas as pd
from .domain import minutes_between

CONTEXT_SCHEMA = "cgm13-context-v2"
CLEAN_CONTEXT_SCHEMA = "cgm13-context-clean-v2"
CONTEXT_FEATURES = ["meal_entries_3h", "meal_minutes_since_6h", "meal_starch_entries_3h",
                    "meal_fruit_entries_3h", "meal_portion_g_3h", "meal_volume_ml_3h",
                    "sc_insulin_entries_6h", "sc_insulin_minutes_since_6h", "sc_insulin_documented_iu_6h",
                    "noninsulin_med_entries_6h", "metformin_entries_6h", "sulfonylurea_entries_6h",
                    "csii_bolus_entries_6h", "csii_basal_entries_6h", "iv_insulin_entries_6h"]


def text(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return None if value.lower() in ("", "/", "nan", "none", "-", "na") else value


def extract_events(frame):
    """One event per source cell; English diet is primary, Chinese is retained."""
    result = []
    prefixes = {"Dietary intake": "meal", "Insulin dose - s.c.": "insulin_sc",
                "Non-insulin hypoglycemic agents": "noninsulin_med", "CSII - bolus": "csii_bolus",
                "CSII - basal": "csii_basal", "Insulin dose - i.v.": "insulin_iv"}
    for index, row in frame.iterrows():
        timestamp = pd.to_datetime(row.get("Date"), errors="coerce")
        if pd.isna(timestamp):
            continue
        at = timestamp.tz_localize("Asia/Shanghai").isoformat()
        for column in frame.columns:
            kind = next((kind for prefix, kind in prefixes.items() if column.startswith(prefix)), None)
            raw = text(row[column])
            if not kind or not raw:
                continue
            if raw.startswith("CSII -"):
                continue  # Repeated column header embedded in a data cell.
            lower = raw.lower()
            payload = {"source_column": column, "raw": raw, "availability_assumption": "source row time"}
            if kind == "meal":
                payload.update(alternate_text=text(row.get("\u996e\u98df")),
                    portion_g=sum(float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*g\b", lower)) or None,
                    volume_ml=sum(float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*ml\b", lower)) or None,
                    starch=bool(re.search(r"rice|bread|noodle|dumpling|porridge|bun|potato|corn|oat", lower)),
                    fruit=bool(re.search(r"apple|banana|orange|pear|grape|melon|peach|fruit", lower)))
            elif kind == "insulin_sc":
                # Do not sum basal rates, IV doses, or CSII boluses into SC units.
                units = re.findall(r"(\d+(?:\.\d+)?)\s*(?:iu|units?)\b", lower)
                payload["documented_iu"] = sum(map(float, units)) if units else None
            elif kind == "noninsulin_med":
                payload.update(metformin="metformin" in lower,
                    sulfonylurea=bool(re.search(r"gliclazide|glimepiride|glipizide|glibenclamide|glyburide", lower)))
            result.append({"source_key": f"{index}:{column}", "time": at, "kind": kind, "payload": payload})
    return sorted(result, key=lambda e: (e["time"], e["source_key"]))


def context_features(events: list[dict], at: str, observed_since: str) -> dict:
    # Defense in depth: even a caller passing the entire archive cannot use future entries.
    past = [e for e in events if observed_since <= e["time"] <= at and 0 <= minutes_between(at, e["time"]) <= 360]
    groups = {kind: [e for e in past if e["kind"] == kind] for kind in
              ("meal", "insulin_sc", "noninsulin_med", "csii_bolus", "csii_basal", "insulin_iv")}
    meals = [e for e in groups["meal"] if minutes_between(at, e["time"]) <= 180]
    oral = groups["noninsulin_med"]
    sc = groups["insulin_sc"]
    def since(entries):
        return min((minutes_between(at, e["time"]) for e in entries), default=None)
    def amount(entries, key):
        # Unknown amounts stay missing, including mixed known/unknown portions.
        values = [e["payload"].get(key) for e in entries]
        return sum(values) if values and all(v is not None for v in values) else None
    return {"meal_entries_3h": len(meals), "meal_minutes_since_6h": since(groups["meal"]),
            "meal_starch_entries_3h": sum(e["payload"].get("starch", False) for e in meals),
            "meal_fruit_entries_3h": sum(e["payload"].get("fruit", False) for e in meals),
            "meal_portion_g_3h": amount(meals, "portion_g"), "meal_volume_ml_3h": amount(meals, "volume_ml"),
            "sc_insulin_entries_6h": len(sc), "sc_insulin_minutes_since_6h": since(sc),
            "sc_insulin_documented_iu_6h": amount(sc, "documented_iu"),
            "noninsulin_med_entries_6h": len(oral), "metformin_entries_6h": sum(e["payload"].get("metformin", False) for e in oral),
            "sulfonylurea_entries_6h": sum(e["payload"].get("sulfonylurea", False) for e in oral),
            "csii_bolus_entries_6h": len(groups["csii_bolus"]), "csii_basal_entries_6h": len(groups["csii_basal"]),
            "iv_insulin_entries_6h": len(groups["insulin_iv"])}
