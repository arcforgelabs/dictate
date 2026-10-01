"""Speech-to-text backend exports."""

from dictate.stt.base import (
    COMPUTE_TYPES,
    ComputeType,
    SpeechToText,
    SttBackend,
    SttCapabilities,
    TranscriptSegment,
    add_retired_device_argument,
    is_cpu_device_name,
    note_retired_device,
)
from dictate.stt.factory import (
    BACKEND_REGISTRY,
    DEFAULT_MEETING_BACKEND,
    DEFAULT_MODELS,
    PARAKEET_DIARIZEN_MODELS,
    PARAKEET_PYANNOTE_MODELS,
    PARAKEET_SORTFORMER_MODELS,
    PARAKEET_MODELS,
    STT_BACKENDS,
    BackendReadiness,
    check_backend_readiness,
    create_speech_to_text,
    resolve_default_local_backend,
    resolve_model_name,
    saved_compute_type,
    saved_meeting_selection,
    saved_stt_selection,
)
from dictate.stt.parakeet_backend import ParakeetSpeechToText
from dictate.stt.parakeet_pyannote_backend import ParakeetPyannoteSpeechToText
from dictate.stt.parakeet_speaker_backend import (
    ParakeetDiariZenSpeechToText,
    ParakeetSortformerSpeechToText,
)

__all__ = [
    "BACKEND_REGISTRY",
    "DEFAULT_MEETING_BACKEND",
    "DEFAULT_MODELS",
    "PARAKEET_DIARIZEN_MODELS",
    "PARAKEET_PYANNOTE_MODELS",
    "PARAKEET_SORTFORMER_MODELS",
    "PARAKEET_MODELS",
    "STT_BACKENDS",
    "BackendReadiness",
    "COMPUTE_TYPES",
    "ComputeType",
    "ParakeetSpeechToText",
    "ParakeetPyannoteSpeechToText",
    "ParakeetDiariZenSpeechToText",
    "ParakeetSortformerSpeechToText",
    "SpeechToText",
    "SttBackend",
    "SttCapabilities",
    "TranscriptSegment",
    "add_retired_device_argument",
    "check_backend_readiness",
    "create_speech_to_text",
    "is_cpu_device_name",
    "note_retired_device",
    "resolve_default_local_backend",
    "resolve_model_name",
    "saved_compute_type",
    "saved_meeting_selection",
    "saved_stt_selection",
]
