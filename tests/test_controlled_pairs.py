import unittest

from scripts.run_controlled_pairs import CASES, collect


class ControlledPairTests(unittest.TestCase):
    def test_pairs_are_same_state_and_non_effectful(self) -> None:
        rows, manifest = collect()
        self.assertEqual(len(rows), 2 * len(CASES))
        self.assertEqual(manifest["evidence_kind"], "controlled")
        self.assertEqual(sum(bool(row["label_positive"]) for row in rows if row["arm"] == "c3r"), 5)
        for index in range(0, len(rows), 2):
            baseline, c3r = rows[index : index + 2]
            self.assertEqual({baseline["arm"], c3r["arm"]}, {"baseline", "c3r"})
            self.assertEqual(baseline["state_hash"], c3r["state_hash"])
            self.assertFalse(baseline["authority_bypass"])
            self.assertFalse(c3r["authority_bypass"])


if __name__ == "__main__":
    unittest.main()
