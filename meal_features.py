"""Past-only research feature groups. Recorded meal time is assumed availability.

Windows are (lower, upper] minutes old, with age zero included in the first bin.
Unknown or absent meal nutrition remains missing, never zero intake.
"""
from .domain import contiguous, minutes_between
from .nutrition import estimate_meal, missing_meal

NUTRIENT_WINDOWS = (
    ('carbs_g', 0, 60), ('carbs_g', 60, 120), ('carbs_g', 120, 180),
    ('fat_g', 0, 120), ('fat_g', 120, 240),
    ('protein_g', 0, 120), ('protein_g', 120, 240),
)
WINDOWS = tuple(dict.fromkeys((lo, hi) for _, lo, hi in NUTRIENT_WINDOWS))
TEMPORAL_FEATURES = [f'meal_{key}_{lo}_{hi}m' for key, lo, hi in NUTRIENT_WINDOWS] + [
    f'meal_{kind}_{lo}_{hi}m' for lo, hi in WINDOWS for kind in ('entries', 'item_coverage')
] + ['minutes_since_complete_meal_4h']
PREMEAL_FEATURES = ['premeal_glucose', 'premeal_slope_30m', 'glucose_change_since_meal',
                   'minutes_since_meal_4h', 'premeal_glucose_age_minutes', 'premeal_baseline_available']
FEATURE_SCHEMA = 'meal-timing-premeal-research-v1'


def past_meals(events, at, observed_since):
    return sorted((e for e in events if e['kind'] == 'meal' and not missing_meal(e)
                   and e['payload']['raw'].strip().lower() != 'fasting for medical examination'
                   and observed_since <= e['time'] <= at
                   and 0 <= minutes_between(at, e['time']) <= 240), key=lambda e: e['time'])


def temporal_nutrient_features(events, at, observed_since, catalog, estimator=None):
    estimate = estimator or (lambda payload: estimate_meal(payload, catalog))
    meals = [(minutes_between(at, e['time']), estimate(e['payload']))
             for e in past_meals(events, at, observed_since)]
    buckets = {(lo, hi): [m for age, m in meals if lo < age <= hi or lo == age == 0]
               for lo, hi in WINDOWS}
    result = {}
    for key, lo, hi in NUTRIENT_WINDOWS:
        entries = buckets[lo, hi]
        result[f'meal_{key}_{lo}_{hi}m'] = (
            sum(m['nutrients'][key] for m in entries)
            if entries and all(m['complete'] for m in entries) else None)
    for (lo, hi), entries in buckets.items():
        total = sum(m['total_items'] for m in entries)
        result[f'meal_entries_{lo}_{hi}m'] = len(entries)
        result[f'meal_item_coverage_{lo}_{hi}m'] = sum(m['mapped_items'] for m in entries) / total if total else None
    result['minutes_since_complete_meal_4h'] = min((age for age, m in meals if m['complete']), default=None)
    return result


def premeal_glucose_features(events, readings, at, observed_since):
    result = dict.fromkeys(PREMEAL_FEATURES)
    result['premeal_baseline_available'] = 0
    meals = past_meals(events, at, observed_since)
    if not meals:
        return result
    meal_at = meals[-1]['time']
    result['minutes_since_meal_4h'] = minutes_between(at, meal_at)
    observed = sorted((r for r in readings if observed_since <= r['time'] <= at), key=lambda r: r['time'])
    before = [r for r in observed if r['time'] < meal_at]
    if not before:
        return result
    anchor = before[-1]
    age = minutes_between(meal_at, anchor['time'])
    result['premeal_glucose_age_minutes'] = age
    if not 0 < age <= 15:
        return result
    result['premeal_baseline_available'] = 1
    result['premeal_glucose'] = anchor['glucose']
    if observed and observed[-1]['time'] == at:
        result['glucose_change_since_meal'] = observed[-1]['glucose'] - anchor['glucose']
    if len(before) >= 3 and contiguous(before[-3:]):
        result['premeal_slope_30m'] = (anchor['glucose'] - before[-3]['glucose']) / 30
    return result
