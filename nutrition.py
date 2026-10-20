"""Offline, versioned estimates. Unknown food/portion/recipe is never zero intake."""
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path
from sqlalchemy import select
from .domain import minutes_between

NUTRITION_SCHEMA = "cgm13-nutrition-v3"
NUTRIENT_KEYS = ["carbs_g", "protein_g", "fat_g", "fibre_g", "energy_kcal"]
NUTRITION_FEATURES = [f"estimated_{key}_{period}" for period in ("last_meal", "3h") for key in NUTRIENT_KEYS] + [
    "nutrition_item_coverage_3h", "nutrition_complete_meals_3h", "nutrition_assumed_items_3h",
    "nutrition_unmapped_items_3h", "nutrition_portion_conversions_3h"]


def missing_meal(event):
    return event["kind"] == "meal" and event["payload"]["raw"].strip().lower() in ("data not available", "not recorded", "\u672a\u8bb0\u5f55")


def catalog_digest(catalog):
    return hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def import_catalog(path: Path):
    from .db import Session, NutritionCatalog, NutritionReference, AuditEvent
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema") != "nutrition-lookup-v1" or not catalog.get("references"):
        raise ValueError("Invalid nutrition catalog")
    for ref in catalog["references"].values():
        if set(ref["nutrients_per_100g"]) != set(NUTRIENT_KEYS):
            raise ValueError("Catalog reference has missing nutrients")
        if any(not isinstance(v, (int, float)) or not 0 <= v <= 1000 for v in ref["nutrients_per_100g"].values()):
            raise ValueError("Invalid nutrient amount")
    digest = catalog_digest(catalog)
    with Session.begin() as db:
        if db.get(NutritionCatalog, digest) is None:
            db.add(NutritionCatalog(id=digest, payload=catalog))
            db.flush()
            for key, ref in catalog["references"].items():
                db.add(NutritionReference(id=f"{digest}:{key}", catalog_id=digest, reference_key=key,
                    description=ref["description"], nutrients=ref["nutrients_per_100g"], portions=ref["portions"], provenance=ref))
            db.add(AuditEvent(kind="nutrition_catalog_imported", entity_id=digest,
                              details={"references": len(catalog["references"]), "source": catalog["source"]}))
    return {"catalog_id": digest, "references": len(catalog["references"]), "mapped_names": len(catalog["mappings"])}


def latest_catalog(db):
    from .db import NutritionCatalog
    catalog = db.scalar(select(NutritionCatalog).order_by(NutritionCatalog.created_at.desc()).limit(1))
    if catalog is None:
        raise ValueError("Import a nutrition catalog first")
    return catalog.id, catalog.payload


def normalize_name(name):
    return re.sub(r"\s+", " ", name).strip(" ,;-").lower()


def portion_grams(amount, unit, ref):
    if unit == "g":
        return amount, False
    if unit == "kg":
        return amount * 1000, True
    if unit == "ml":
        # Derived food-specific approximation from a USDA US-cup serving, not 1 mL=1 g for all foods.
        cup = next((p for p in ref["portions"] if p.get("description", "").lower() == "1 cup"), None)
        return (amount * cup["gram_weight"] / 236.5882365, True) if cup else (None, True)
    if unit in ("piece", "pieces", "egg", "eggs", "cup", "cups"):
        singular = {"pieces": "piece", "eggs": "egg", "cups": "cup"}.get(unit, unit)
        match = next((p for p in ref["portions"] if p.get("description", "").lower() == f"1 {singular}"), None)
        return (amount * match["gram_weight"], True) if match else (None, True)
    return None, False


@lru_cache(maxsize=12000)
def _meal_estimate(raw, alternate, serialized_catalog):
    catalog = json.loads(serialized_catalog)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    chinese = [line.strip() for line in alternate.splitlines() if line.strip()]
    items = []
    for i, line in enumerate(lines):
        match = re.fullmatch(r"(.*?)\s*(\d+(?:\.\d+)?)\s*(g|ml|kg|pieces?|eggs?|cups?)\s*", line, re.I)
        if not match:
            items.append({"raw": line, "status": "unresolved_portion_or_food"})
            continue
        name, amount, unit = normalize_name(match[1]), float(match[2]), match[3].lower()
        mapping = catalog["mappings"].get(name)
        method, method_source = "unknown", None
        if len(chinese) == len(lines):
            zh = chinese[i]
            # Check quantity agreement before taking a Chinese method from the same line position.
            zh_amount = re.search(r"(\d+(?:\.\d+)?)\s*(g|ml|kg)\s*$", zh, re.I)
            if zh_amount and float(zh_amount[1]) == amount and zh_amount[2].lower() == unit:
                method = next((label for token, label in (("\u84b8", "steamed"), ("\u716e", "boiled"), ("\u7092", "stir_fried"), ("\u714e", "pan_fried"), ("\u70b8", "deep_fried")) if token in zh), "unknown")
                if method != "unknown":
                    method_source = "Chinese line; matched position and portion, food-name agreement remains a mapping assumption"
        if name in ("egg", "eggs") and method in ("stir_fried", "pan_fried", "deep_fried"):
            mapping = catalog["mappings"].get("fried egg")
        elif name in ("egg", "eggs") and method == "boiled":
            mapping = catalog["mappings"].get("boiled egg")
        if not mapping:
            items.append({"raw": line, "food": name, "status": "unmapped_food", "method": method})
            continue
        ref = catalog["references"][mapping["reference"]]
        grams, conversion = portion_grams(amount, unit, ref)
        if grams is None or grams <= 0:
            items.append({"raw": line, "food": name, "status": "unresolved_portion", "reference": mapping["reference"]})
            continue
        items.append({"raw": line, "food": name, "status": "estimated", "grams": grams,
            "reference": mapping["reference"], "assumed": mapping["assumed"], "portion_conversion": conversion,
            "method": method, "method_source": method_source,
            "nutrients": {key: value * grams / 100 for key, value in ref["nutrients_per_100g"].items()}})
    mapped = [item for item in items if item["status"] == "estimated"]
    complete = bool(items) and len(mapped) == len(items)
    return {"items": items, "mapped_items": len(mapped), "total_items": len(items), "complete": complete,
        "assumed_items": sum(item.get("assumed", False) for item in mapped),
        "portion_conversions": sum(item.get("portion_conversion", False) for item in mapped),
        "nutrients": {key: sum(item["nutrients"][key] for item in mapped) if complete else None for key in NUTRIENT_KEYS},
        "known_subtotal": {key: sum(item["nutrients"][key] for item in mapped) for key in NUTRIENT_KEYS}}


_catalog_strings = {}


def estimate_meal(payload, catalog):
    if catalog.get("parser_version") == "dish-lines-v3":
        from .nutrition_v3 import estimate_meal_v3
        return estimate_meal_v3(payload, catalog)
    key = id(catalog)
    if key not in _catalog_strings:
        if len(_catalog_strings) > 16:
            _catalog_strings.clear()
        _catalog_strings[key] = (catalog, json.dumps(catalog, sort_keys=True))
    return _meal_estimate(payload["raw"], payload.get("alternate_text") or "", _catalog_strings[key][1])


def nutrition_features(events, at, observed_since, catalog):
    meals = [e for e in events if e["kind"] == "meal" and not missing_meal(e)
             and observed_since <= e["time"] <= at and 0 <= minutes_between(at, e["time"]) <= 180]
    estimates = [estimate_meal(e["payload"], catalog) for e in sorted(meals, key=lambda e: e["time"])]
    latest = estimates[-1] if estimates else None
    complete_window = bool(estimates) and all(e["complete"] for e in estimates)
    result = {f"estimated_{key}_last_meal": latest["nutrients"][key] if latest else None for key in NUTRIENT_KEYS}
    result.update({f"estimated_{key}_3h": sum(e["nutrients"][key] for e in estimates) if complete_window else None for key in NUTRIENT_KEYS})
    total = sum(e["total_items"] for e in estimates)
    mapped = sum(e["mapped_items"] for e in estimates)
    result.update(nutrition_item_coverage_3h=mapped/total if total else None,
        nutrition_complete_meals_3h=sum(e["complete"] for e in estimates),
        nutrition_assumed_items_3h=sum(e["assumed_items"] for e in estimates),
        nutrition_unmapped_items_3h=total-mapped,
        nutrition_portion_conversions_3h=sum(e["portion_conversions"] for e in estimates))
    return result
