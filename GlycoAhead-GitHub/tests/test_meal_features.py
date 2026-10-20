import unittest

from glycoahead.domain import add_minutes
from glycoahead.meal_features import temporal_nutrient_features, premeal_glucose_features

START = '2026-01-01T00:00:00+08:00'


def event(minute, value=10):
    return {'kind': 'meal', 'time': add_minutes(START, minute),
            'payload': {'raw': 'known food' if value is not None else 'unknown food', 'value': value}}


def estimate(payload):
    v = payload['value']
    return {'complete': v is not None, 'total_items': 1, 'mapped_items': int(v is not None),
            'nutrients': {'carbs_g': v, 'fat_g': v, 'protein_g': v}}


def temporal(events, minute=240, since=START):
    return temporal_nutrient_features(events, add_minutes(START, minute), since, {}, estimate)


class MealFeaturesTest(unittest.TestCase):
    def test_boundaries_do_not_double_count(self):
        f = temporal([event(240, 1), event(180, 2), event(120, 4), event(60, 8), event(0, 16)])
        self.assertEqual(f['meal_carbs_g_0_60m'], 3)
        self.assertEqual(f['meal_carbs_g_60_120m'], 4)
        self.assertEqual(f['meal_carbs_g_120_180m'], 8)
        self.assertEqual(f['meal_fat_g_0_120m'], 7)
        self.assertEqual(f['meal_fat_g_120_240m'], 24)

    def test_future_meal_cannot_change_features(self):
        history = [event(200, 25)]
        self.assertEqual(temporal(history), temporal(history + [event(241, 9999)]))

    def test_absence_unknown_and_known_zero_differ(self):
        self.assertIsNone(temporal([])['meal_carbs_g_0_60m'])
        unknown = temporal([event(230, None), event(220, 20)])
        self.assertIsNone(unknown['meal_carbs_g_0_60m'])
        self.assertEqual(unknown['meal_item_coverage_0_60m'], .5)
        self.assertEqual(unknown['minutes_since_complete_meal_4h'], 20)
        self.assertEqual(temporal([event(230, 0)])['meal_carbs_g_0_60m'], 0)

    def test_gap_discards_previous_meals(self):
        f = temporal([event(180, 30)], since=add_minutes(START, 200))
        self.assertIsNone(f['minutes_since_complete_meal_4h'])
        self.assertEqual(f['meal_entries_0_60m'], 0)

    def test_fasting_note_does_not_create_a_meal(self):
        fasting = event(230)
        fasting['payload']['raw'] = 'Fasting for medical examination'
        self.assertEqual(temporal([fasting]), temporal([]))
        f = premeal_glucose_features([fasting], [], add_minutes(START, 240), START)
        self.assertIsNone(f['minutes_since_meal_4h'])

    def test_premeal_uses_strictly_earlier_glucose(self):
        readings = [{'time': add_minutes(START, t), 'glucose': g}
                    for t, g in [(0, 100), (15, 110), (30, 120), (45, 500), (60, 140), (75, 999)]]
        f = premeal_glucose_features([event(45)], readings, add_minutes(START, 60), START)
        self.assertEqual(f['premeal_glucose'], 120)
        self.assertAlmostEqual(f['premeal_slope_30m'], 20/30)
        self.assertEqual(f['glucose_change_since_meal'], 20)
        self.assertEqual(f['premeal_glucose_age_minutes'], 15)
        self.assertEqual(f['premeal_baseline_available'], 1)

    def test_stale_anchor_and_discontinuous_trend(self):
        readings = [{'time': add_minutes(START, t), 'glucose': 120} for t in [0, 30, 60]]
        stale = premeal_glucose_features([event(50)], readings, add_minutes(START, 60), START)
        self.assertEqual(stale['premeal_baseline_available'], 0)
        self.assertIsNone(stale['premeal_glucose'])
        f = premeal_glucose_features([event(40)], readings, add_minutes(START, 60), START)
        self.assertEqual(f['premeal_baseline_available'], 1)
        self.assertIsNone(f['premeal_slope_30m'])

    def test_archive_and_observed_prefix_agree(self):
        readings = [{'time': add_minutes(START, t), 'glucose': 100+t/20} for t in range(0, 721, 15)]
        meals = [event(30, 20), event(270, 50), event(400, 30), event(630, 80)]
        for i in range(12, len(readings)):
            at = readings[i]['time']
            prefix = readings[max(0, i-31):i+1]
            available = [e for e in meals if e['time'] <= at]
            self.assertEqual(premeal_glucose_features(meals, readings, at, START),
                             premeal_glucose_features(available, prefix, at, START))
            self.assertEqual(temporal_nutrient_features(meals, at, START, {}, estimate),
                             temporal_nutrient_features(available, at, START, {}, estimate))


if __name__ == '__main__':
    unittest.main()
