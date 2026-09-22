import unittest

from c3r.deliberative import (
    DEFAULT_LANGUAGE_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    default_provider_config,
)


class DefaultLanguageModelTests(unittest.TestCase):
    def test_openrouter_is_the_default_gateway(self) -> None:
        config = default_provider_config(api_key="test-key")
        self.assertEqual(DEFAULT_LANGUAGE_MODEL, "deepseek-ai/DeepSeek-V4.1-Flash")
        self.assertEqual(config.model, DEFAULT_OPENROUTER_MODEL)
        self.assertEqual(config.base_url, "https://openrouter.ai/api/v1")

    def test_direct_deepseek_uses_official_alias(self) -> None:
        config = default_provider_config(api_key="test-key", gateway="deepseek")
        self.assertEqual(config.model, "deepseek-flash")
        self.assertEqual(config.base_url, "https://api.deepseek.com")

    def test_credentials_are_never_optional(self) -> None:
        with self.assertRaises(ValueError):
            default_provider_config(api_key="")


if __name__ == "__main__":
    unittest.main()
