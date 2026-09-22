import unittest

from c3r.feature_flags import FeatureFlags


class FeatureFlagTests(unittest.TestCase):
    def test_global_disable_turns_off_every_learned_control_surface(self) -> None:
        flags = FeatureFlags.from_mapping(
            {
                "C3R_ENABLED": "false",
                "C3R_SYSTEM_ONE": "true",
                "C3R_DELIBERATIVE": "true",
                "C3R_ROUTING": "true",
                "C3R_SPECULATION": "true",
                "C3R_MOE_CONTROL": "true",
            }
        )

        self.assertFalse(flags.system_one_enabled)
        self.assertFalse(flags.deliberative_enabled)
        self.assertFalse(flags.routing_enabled)
        self.assertFalse(flags.speculation_enabled)
        self.assertFalse(flags.moe_control_enabled)

    def test_online_learning_cannot_be_enabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "online learning"):
            FeatureFlags.from_mapping({"C3R_ONLINE_LEARNING": "true"})

    def test_invalid_boolean_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "C3R_SYSTEM_ONE"):
            FeatureFlags.from_mapping({"C3R_SYSTEM_ONE": "sometimes"})


if __name__ == "__main__":
    unittest.main()
