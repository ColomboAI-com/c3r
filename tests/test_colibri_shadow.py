import unittest

from c3r.colibri import ColibriAction, ColibriShadowController, ColibriSnapshot


class ColibriShadowTests(unittest.TestCase):
    def test_shadow_recommendation_never_has_native_authority(self) -> None:
        controller = ColibriShadowController(minimum_acceptance=0.65)
        result = controller.recommend(
            ColibriSnapshot(
                route_trace="trace-1",
                coli_usage=0.8,
                dspark_acceptance=0.4,
                verification_width=2,
                expert_union=8,
                cache_residency=0.7,
                expert_hit_rate=0.6,
                bytes_read=4096,
                io_rate=100.0,
                cpu_utilization=0.4,
                gpu_utilization=0.7,
                context_length=2048,
            )
        )

        self.assertEqual(result.action, ColibriAction.TARGET_ONLY)
        self.assertFalse(result.authoritative)
        self.assertEqual(result.route_trace, "trace-1")

    def test_controller_failure_returns_native_fallback(self) -> None:
        controller = ColibriShadowController()

        result = controller.fallback("controller timeout")

        self.assertEqual(result.action, ColibriAction.NATIVE_FALLBACK)
        self.assertFalse(result.authoritative)
        self.assertIn("timeout", result.reason)


if __name__ == "__main__":
    unittest.main()
