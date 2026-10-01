from __future__ import annotations

import unittest

from dictate.lexicon import (
    DEFAULT_LEXICON_MODE,
    apply_post_corrections,
    build_lexicon_plan,
    normalize_lexicon_mode,
)
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

    def test_default_mode_is_hybrid_so_saved_hotwords_apply(self) -> None:
        # No backend decodes hotwords natively (issue #100); the default must still
        # route saved hotwords through post-correction.
        self.assertEqual(DEFAULT_LEXICON_MODE, "hybrid")
        self.assertEqual(normalize_lexicon_mode(None), "hybrid")
        self.assertEqual(normalize_lexicon_mode("bogus"), "hybrid")
        self.assertEqual(normalize_lexicon_mode("native"), "native")

    def test_default_mode_post_corrects_without_native_hotword_support(self) -> None:
        class _NoHotwords(_DummySpeechToText):
            capabilities = SttCapabilities(supports_hotwords=False, supports_prompt_bias=False)

        plan = build_lexicon_plan(
            stt=_NoHotwords(),
            hotwords="Quillmate",
            lexicon_mode=DEFAULT_LEXICON_MODE,
        )
        self.assertIsNone(plan.decode_hotwords)
        self.assertEqual(plan.post_hotwords, ("Quillmate",))

    def test_no_hotwords_leaves_text_untouched(self) -> None:
        text = "just the same page in the dark park"
        self.assertEqual(apply_post_corrections(text, hotwords=(), replacements={}), text)

    def test_short_hotwords_never_fuzzy_match_everyday_words(self) -> None:
        hotwords = ("Sage", "Mark", "Bree", "Rust", "BAS", "Pip")
        text = "Just save the same page, it is free, the park is dark and the base must rest"
        self.assertEqual(apply_post_corrections(text, hotwords=hotwords, replacements={}), text)

    def test_short_title_case_hotwords_do_not_recase_everyday_words(self) -> None:
        hotwords = ("Mark", "Rust", "Sage", "Pip")
        text = "put a mark by the rust, add sage, and spit out the pip"
        self.assertEqual(apply_post_corrections(text, hotwords=hotwords, replacements={}), text)
        self.assertEqual(
            apply_post_corrections("Mark said hi", hotwords=hotwords, replacements={}),
            "Mark said hi",
        )

    def test_short_acronyms_are_still_recased(self) -> None:
        self.assertEqual(
            apply_post_corrections(
                "lodge the gst and check the sla",
                hotwords=("GST", "SLA"),
                replacements={},
            ),
            "lodge the GST and check the SLA",
        )

    def test_two_letter_acronyms_do_not_recase_common_words(self) -> None:
        text = "tell us if it works"
        self.assertEqual(
            apply_post_corrections(text, hotwords=("US", "IT"), replacements={}),
            text,
        )

    def test_longer_hotwords_still_repair_one_edit_near_misses(self) -> None:
        corrected = apply_post_corrections(
            "the quilmate build and kubernetis with Pria and Tomas",
            hotwords=("Quillmate", "Kubernetes", "Priya", "Tomasz"),
            replacements={},
        )
        self.assertEqual(corrected, "the Quillmate build and Kubernetes with Priya and Tomasz")

    def test_explicit_replacements_apply_regardless_of_length(self) -> None:
        self.assertEqual(
            apply_post_corrections("send it to reece", hotwords=(), replacements={"reece": "Rhys"}),
            "send it to Rhys",
        )


if __name__ == "__main__":
    unittest.main()
