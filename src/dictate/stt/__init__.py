"""Speech-to-text backend exports."""

from dictate.stt.base import (
    ComputeDevice,
    ComputeType,
    FasterWhisperModel,
    SpeechToText,
    SttBackend,
    SttCapabilities,
    WhisperCppModel,
)
from dictate.stt.factory import (
    BACKEND_REGISTRY,
    DEFAULT_MODELS,
    FASTER_WHISPER_MODELS,
    NEMO_CANARY_MODELS,
    STT_BACKENDS,
    WHISPER_CPP_MODELS,
    BackendReadiness,
    check_backend_readiness,
    create_speech_to_text,
    resolve_model_name,
)
from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText
from dictate.stt.nemo_canary_backend import NeMoCanarySpeechToText
from dictate.stt.whisper_cpp_backend import WhisperCppSpeechToText

__all__ = [
    "BACKEND_REGISTRY",
    "DEFAULT_MODELS",
    "FASTER_WHISPER_MODELS",
    "NEMO_CANARY_MODELS",
    "STT_BACKENDS",
    "WHISPER_CPP_MODELS",
    "BackendReadiness",
    "ComputeDevice",
    "ComputeType",
    "FasterWhisperModel",
    "FasterWhisperSpeechToText",
    "NeMoCanarySpeechToText",
    "SpeechToText",
    "SttBackend",
    "SttCapabilities",
    "WhisperCppModel",
    "WhisperCppSpeechToText",
    "check_backend_readiness",
    "create_speech_to_text",
    "resolve_model_name",
]
