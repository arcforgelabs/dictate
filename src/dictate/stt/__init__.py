"""Speech-to-text backend exports."""

from dictate.stt.base import (
    COMPUTE_DEVICES,
    COMPUTE_TYPES,
    ComputeDevice,
    ComputeType,
    FasterWhisperModel,
    SpeechToText,
    SttBackend,
    SttCapabilities,
    TranscriptSegment,
    ONNX_AMD_PROVIDERS,
    WhisperCppModel,
)
from dictate.stt.factory import (
    BACKEND_REGISTRY,
    DEFAULT_MODELS,
    FASTER_WHISPER_MODELS,
    PARAKEET_DIARIZEN_MODELS,
    PARAKEET_PYANNOTE_MODELS,
    PARAKEET_SORTFORMER_MODELS,
    PARAKEET_MODELS,
    STT_BACKENDS,
    WHISPERX_MODELS,
    BackendReadiness,
    check_backend_readiness,
    create_speech_to_text,
    resolve_default_local_backend,
    resolve_default_local_model,
    resolve_model_name,
)
from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText
from dictate.stt.parakeet_backend import ParakeetSpeechToText
from dictate.stt.parakeet_pyannote_backend import ParakeetPyannoteSpeechToText
from dictate.stt.parakeet_speaker_backend import (
    ParakeetDiariZenSpeechToText,
    ParakeetSortformerSpeechToText,
)
from dictate.stt.whisperx_backend import WhisperXSpeechToText

__all__ = [
    "BACKEND_REGISTRY",
    "DEFAULT_MODELS",
    "FASTER_WHISPER_MODELS",
    "ONNX_AMD_PROVIDERS",
    "PARAKEET_DIARIZEN_MODELS",
    "PARAKEET_PYANNOTE_MODELS",
    "PARAKEET_SORTFORMER_MODELS",
    "PARAKEET_MODELS",
    "STT_BACKENDS",
    "WHISPERX_MODELS",
    "BackendReadiness",
    "COMPUTE_DEVICES",
    "COMPUTE_TYPES",
    "ComputeDevice",
    "ComputeType",
    "FasterWhisperModel",
    "FasterWhisperSpeechToText",
    "ParakeetSpeechToText",
    "ParakeetPyannoteSpeechToText",
    "ParakeetDiariZenSpeechToText",
    "ParakeetSortformerSpeechToText",
    "SpeechToText",
    "SttBackend",
    "SttCapabilities",
    "TranscriptSegment",
    "WhisperCppModel",
    "WhisperXSpeechToText",
    "check_backend_readiness",
    "create_speech_to_text",
    "resolve_default_local_backend",
    "resolve_default_local_model",
    "resolve_model_name",
]
