"""xAI hosted speech-to-text backend adapter."""

from __future__ import annotations

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


class XAISpeechToText(SpeechToText):
    """Remote transcription through xAI Speech to Text."""

    backend_name = "xai"
    capabilities = SttCapabilities(
        supports_hotwords=True,
        supports_prompt_bias=False,
        supports_language_hint=True,
        supports_word_timestamps=True,
    )

    def __init__(
        self,
        model_name: str = "grok-speech-to-text",
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
        del prompt_context
        with tempfile.TemporaryDirectory(prefix="dictate-xai-") as temp_dir:
            wav_path = Path(temp_dir) / "audio.wav"
            _write_wav(wav_path, audio)
            fields: list[tuple[str, str]] = []
            if language:
                fields.extend([("format", "true"), ("language", language)])
            for keyterm in _keyterms(hotwords):
                fields.append(("keyterm", keyterm))

            response = _post_multipart(
                url=f"{_base_url()}/stt",
                api_key=self.api_key,
                file_path=wav_path,
                fields=fields,
                timeout=_timeout_seconds(audio),
            )
        return _extract_text(response)


def _api_key() -> str:
    api_key = os.environ.get("DICTATE_XAI_API_KEY") or os.environ.get("XAI_API_KEY")
    if not api_key:
        api_key = _api_key_from_command()
    if not api_key:
        raise RuntimeError(
            "xAI STT backend selected but no API key is configured. "
            "Set DICTATE_XAI_API_KEY, XAI_API_KEY, or DICTATE_XAI_API_KEY_COMMAND."
        )
    return api_key


def xai_api_key_available() -> bool:
    try:
        return bool(_api_key())
    except Exception:
        return False


def _api_key_from_command() -> str | None:
    command = os.environ.get("DICTATE_XAI_API_KEY_COMMAND")
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
        raise RuntimeError("xAI API key command failed.") from exc
    output = completed.stdout.strip()
    if not output:
        return None
    return output.splitlines()[0].strip() or None


def _base_url() -> str:
    return os.environ.get("DICTATE_XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")


def _keyterms(hotwords: str | None) -> list[str]:
    if not hotwords:
        return []
    terms: list[str] = []
    for raw in hotwords.replace(";", "\n").replace(",", "\n").splitlines():
        term = " ".join(raw.split())
        if term and len(term) <= 50:
            terms.append(term)
    return terms[:100]


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


def _post_multipart(
    *,
    url: str,
    api_key: str,
    file_path: Path,
    fields: list[tuple[str, str]],
    timeout: int,
) -> str:
    boundary = f"----dictate-xai-{os.getpid()}-{time.time_ns()}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"xAI transcription returned HTTP {exc.code}: {detail}") from exc


def _extract_text(response: str) -> str:
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return response.strip()

    text = data.get("text")
    if isinstance(text, str):
        return text.strip()
    return response.strip()
