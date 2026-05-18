from __future__ import annotations

import unittest

from dictate.lexicon import apply_post_corrections, build_lexicon_plan
from dictate.stt import SpeechToText, SttCapabilities


class _DummySpeechToText(SpeechToText):
    backend_name = "dummy"
    capabilities = SttCapabilities(supports_hotwords=True, supports_prompt_bias=True)

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language, hotwords, prompt_context
        return ""


class LexiconTests(unittest.TestCase):
    def test_hybrid_plan_enables_all_channels(self) -> None:
        stt = _DummySpeechToText()
        plan = build_lexicon_plan(
            stt=stt,
            hotwords="AcmeWidget canary",
            lexicon_mode="hybrid",
            replacements={"kinneri": "canary"},
        )

        self.assertEqual(plan.decode_hotwords, "AcmeWidget canary")
        self.assertIsNotNone(plan.prompt_context)
        self.assertEqual(plan.post_hotwords, ("AcmeWidget", "canary"))
        self.assertEqual(plan.post_replacements, {"kinneri": "canary"})

    def test_apply_post_corrections_prefers_explicit_map(self) -> None:
        corrected = apply_post_corrections(
            "Testing kinneri and canery now",
            hotwords=("canary",),
            replacements={"kinneri": "canary"},
        )
        self.assertEqual(corrected, "Testing canary and canary now")


if __name__ == "__main__":
    unittest.main()
