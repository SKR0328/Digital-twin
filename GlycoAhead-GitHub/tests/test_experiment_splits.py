import unittest
from glycoahead.experiments import patient_splits


class PatientSplitTest(unittest.TestCase):
    def test_all_visits_share_one_patient_assignment(self):
        patients = [str(i) for i in range(100)]
        splits = patient_splits(patients + patients[:9], 2026)
        self.assertEqual([len(x) for x in splits.values()], [60, 10, 10, 20])
        flattened = [p for group in splits.values() for p in group]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), set(patients))
        for patient in patients[:9]:
            self.assertEqual(sum(patient in group for group in splits.values()), 1)

    def test_seed_reproducibility_and_alternative_assignments(self):
        ids = [str(i) for i in range(100)]
        self.assertEqual(patient_splits(ids, 2026), patient_splits(list(reversed(ids)), 2026))
        self.assertNotEqual(patient_splits(ids, 2026), patient_splits(ids, 2027))


if __name__ == '__main__':
    unittest.main()
