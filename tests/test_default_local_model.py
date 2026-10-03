from __future__ import annotations

import unittest

from dictate.stt import factory as stt_factory


class ResolveDefaultLocalBackendTests(unittest.TestCase):
    def test_defaults_to_parakeet(self) -> None:
        self.assertEqual(
            stt_factory.resolve_default_local_backend(),
            ("parakeet", "parakeet-tdt-0.6b-v2"),
        )


class SavedSelectionMigrationTests(unittest.TestCase):
    def test_registered_backend_keeps_saved_model(self) -> None:
        self.assertEqual(
            stt_factory.saved_stt_selection("parakeet", "parakeet-tdt-0.6b-v3"),
            ("parakeet", "parakeet-tdt-0.6b-v3"),
        )

    def test_removed_whisper_backends_are_unset_with_their_model(self) -> None:
        for backend, model in (
            ("faster-whisper", "turbo"),
            ("whisperx", "large-v3"),
            ("faster-whisper", None),
        ):
            with self.subTest(backend=backend):
                self.assertEqual(stt_factory.saved_stt_selection(backend, model), (None, None))

    def test_unset_backend_drops_legacy_model(self) -> None:
        # An unset backend used to mean faster-whisper, so its model is a Whisper name.
        self.assertEqual(stt_factory.saved_stt_selection(None, "small"), (None, None))

    def test_unset_backend_keeps_a_parakeet_model(self) -> None:
        # config/default-config.yaml offers `stt_model: parakeet-tdt-0.6b-v3` on its own.
        for model in stt_factory.PARAKEET_MODELS:
            with self.subTest(model=model):
                self.assertEqual(stt_factory.saved_stt_selection(None, model), ("parakeet", model))
                self.assertEqual(stt_factory.saved_stt_selection("", model), ("parakeet", model))

    def test_removed_backend_drops_even_a_parakeet_model(self) -> None:
        self.assertEqual(
            stt_factory.saved_stt_selection("faster-whisper", "parakeet-tdt-0.6b-v3"), (None, None)
        )

    def test_meeting_selection_is_gone(self) -> None:
        # Meeting capture was removed (#140).
        self.assertFalse(hasattr(stt_factory, "saved_meeting_selection"))
        self.assertNotIn("parakeet-pyannote", stt_factory.BACKEND_REGISTRY)


if __name__ == "__main__":
    unittest.main()
