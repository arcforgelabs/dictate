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
    GEMINI_MODELS,
    OPENAI_MODELS,
    STT_BACKENDS,
    XAI_MODELS,
    BackendReadiness,
    check_backend_readiness,
    create_speech_to_text,
    resolve_model_name,
)
from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText
from dictate.stt.gemini_backend import GeminiSpeechToText
from dictate.stt.openai_backend import OpenAISpeechToText
from dictate.stt.xai_backend import XAISpeechToText

__all__ = [
    "BACKEND_REGISTRY",
    "DEFAULT_MODELS",
    "FASTER_WHISPER_MODELS",
    "GEMINI_MODELS",
    "OPENAI_MODELS",
    "STT_BACKENDS",
    "XAI_MODELS",
    "BackendReadiness",
    "ComputeDevice",
    "ComputeType",
    "FasterWhisperModel",
    "FasterWhisperSpeechToText",
    "GeminiSpeechToText",
    "OpenAISpeechToText",
    "SpeechToText",
    "SttBackend",
    "SttCapabilities",
    "WhisperCppModel",
    "XAISpeechToText",
    "check_backend_readiness",
    "create_speech_to_text",
    "resolve_model_name",
]
