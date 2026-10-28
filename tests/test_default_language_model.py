import unittest

from c3r.deliberative import (
    DEFAULT_LANGUAGE_MODEL,
    default_provider_config,
)


class DefaultLanguageModelTests(unittest.TestCase):
    def test_self_hosted_deepseek_is_the_default_gateway(self) -> None:
        config = default_provider_config()
        self.assertEqual(DEFAULT_LANGUAGE_MODEL, "deepseek-ai/DeepSeek-V4.1-Flash")
        self.assertEqual(config.model, "/model")
        self.assertEqual(config.base_url, "http://127.0.0.1:8000/v1")
        self.assertIsNone(config.api_key)

    def test_direct_deepseek_uses_official_alias(self) -> None:
        config = default_provider_config(api_key="test-key", gateway="deepseek")
        self.assertEqual(config.model, "deepseek-flash")
        self.assertEqual(config.base_url, "https://api.deepseek.com")

    def test_explicit_remote_compatibility_requires_credentials(self) -> None:
        with self.assertRaises(ValueError):
            default_provider_config(api_key="", gateway="deepseek")


if __name__ == "__main__":
    unittest.main()
