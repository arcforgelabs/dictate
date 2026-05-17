"""Google Gemini hosted audio transcription backend adapter."""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

from dictate.stt.base import ComputeDevice, SpeechToText, SttCapabilities


class GeminiSpeechToText(SpeechToText):
    """Remote transcription through Gemini audio understanding."""

    backend_name = "gemini"
    capabilities = SttCapabilities(
        supports_hotwords=False,
        supports_prompt_bias=True,
        supports_language_hint=True,
    )

    def __init__(
        self,
        model_name: str = "gemini-3-flash-preview",
        device: ComputeDevice = "auto",
    ):
        del device
        self.model_name = model_name
        self.api_key = _api_key()

    @property
    def model(self) -> str:
        return self.model_name

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
    ) -> str:
        del hotwords
        with tempfile.TemporaryDirectory(prefix="dictate-gemini-") as temp_dir:
            wav_path = Path(temp_dir) / "audio.wav"
            _write_wav(wav_path, audio)
            response = _post_generate_content(
                url=f"{_base_url()}/models/{self.model_name}:generateContent",
                api_key=self.api_key,
                audio_data=wav_path.read_bytes(),
                prompt=_build_prompt(language=language, prompt_context=prompt_context),
                timeout=_timeout_seconds(audio),
            )
        return _extract_text(response)


def _api_key() -> str:
    api_key = (
        os.environ.get("DICTATE_GEMINI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        api_key = _api_key_from_command()
    if not api_key:
        raise RuntimeError(
            "Gemini STT backend selected but no API key is configured. "
            "Set DICTATE_GEMINI_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY, "
            "or DICTATE_GEMINI_API_KEY_COMMAND."
        )
    return api_key


def gemini_api_key_available() -> bool:
    try:
        return bool(_api_key())
    except Exception:
        return False


def _api_key_from_command() -> str | None:
    command = os.environ.get("DICTATE_GEMINI_API_KEY_COMMAND")
    if not command:
        return None
    try:
        completed = subprocess.run(
            shlex.split(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Gemini API key command failed.") from exc
    output = completed.stdout.strip()
    if not output:
        return None
    return output.splitlines()[0].strip() or None


def _base_url() -> str:
    return os.environ.get(
        "DICTATE_GEMINI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    ).rstrip("/")


def _build_prompt(*, language: str | None, prompt_context: str | None) -> str:
    parts = [
        "Transcribe the speech in this audio accurately.",
        "Return only the spoken transcript text.",
        "Do not summarize, explain, add timestamps, or wrap the transcript in quotes.",
    ]
    if language:
        parts.append(f"The expected language code is {language}.")
    if prompt_context:
        parts.append(prompt_context.strip())
    return " ".join(part for part in parts if part)


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int = 16000) -> None:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def _timeout_seconds(audio: np.ndarray, sample_rate: int = 16000) -> int:
    duration = audio.size / float(sample_rate)
    return max(30, min(300, int(duration * 10) + 20))


def _post_generate_content(
    *,
    url: str,
    api_key: str,
    audio_data: bytes,
    prompt: str,
    timeout: int,
) -> str:
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "audio/wav",
                            "data": base64.b64encode(audio_data).decode("ascii"),
                        }
                    },
                ]
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini transcription returned HTTP {exc.code}: {detail}") from exc


def _extract_text(response: str) -> str:
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return response.strip()

    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return response.strip()
    texts: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"].strip())
    return "\n".join(text for text in texts if text).strip() or response.strip()
