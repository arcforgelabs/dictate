"""whisper.cpp CLI backend adapter."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

from dictate.platform_paths import user_data_dir
from dictate.stt.base import ComputeDevice, SpeechToText, SttCapabilities


class WhisperCppSpeechToText(SpeechToText):
    """Local transcription through a loopback whisper.cpp server."""

    backend_name = "whisper-cpp"
    capabilities = SttCapabilities(
        supports_hotwords=True,
        supports_prompt_bias=True,
        supports_language_hint=True,
    )

    def __init__(
        self,
        model_name: str = "large-v3-turbo-q5_0",
        device: ComputeDevice = "auto",
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = "int8"
        self._server_path: Path | None = None
        self._model_path: Path | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._port: int | None = None

    @property
    def model(self) -> tuple[Path, Path, int]:
        server_path = resolve_whisper_cpp_server()
        model_path = resolve_whisper_cpp_model(self.model_name)
        if not server_path.is_file():
            raise RuntimeError(f"whisper.cpp server executable not found: {server_path}")
        if not model_path.is_file():
            raise RuntimeError(f"whisper.cpp model not found: {model_path}")
        self._server_path = server_path
        self._model_path = model_path
        self._ensure_server_started(server_path=server_path, model_path=model_path)
        return (server_path, model_path, self._port or 0)

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
    ) -> str:
        _server_path, _model_path, port = self.model
        prompt = _build_prompt(hotwords=hotwords, prompt_context=prompt_context)

        with tempfile.TemporaryDirectory(prefix="dictate-whisper-cpp-") as temp_dir:
            temp_path = Path(temp_dir)
            wav_path = temp_path / "audio.wav"
            _write_wav(wav_path, audio)

            fields = {
                "response_format": "json",
                "no_timestamps": "true",
                "beam_size": "1",
                "best_of": "1",
                "temperature": "0.0",
                "suppress_nst": "true",
            }
            fields["language"] = language or "auto"
            if prompt:
                fields["prompt"] = prompt

            response = _post_multipart(
                url=f"http://127.0.0.1:{port}/inference",
                file_path=wav_path,
                fields=fields,
                timeout=_timeout_seconds(audio),
            )
            return _extract_text(response)

    def release(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def _ensure_server_started(self, *, server_path: Path, model_path: Path) -> None:
        if self._process is not None and self._process.poll() is None and self._port is not None:
            return

        port = _configured_port()
        command = [
            str(server_path),
            "-m",
            str(model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "-bs",
            "1",
            "-bo",
            "1",
            "-nt",
        ]
        if self.device == "cpu":
            command.append("--no-gpu")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._port = port
        try:
            _wait_for_server(port=port, process=self._process)
        except Exception:
            self.release()
            raise


def resolve_whisper_cpp_server() -> Path:
    configured = os.environ.get("DICTATE_WHISPER_CPP_SERVER")
    if configured:
        return Path(configured).expanduser()

    return user_data_dir() / "whisper.cpp" / "Release" / "whisper-server.exe"


def resolve_whisper_cpp_model(model_name: str) -> Path:
    configured = os.environ.get("DICTATE_WHISPER_CPP_MODEL")
    if configured:
        return Path(configured).expanduser()

    candidate = Path(model_name).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate

    filename = _model_filename(model_name)
    return user_data_dir() / "models" / filename


def _model_filename(model_name: str) -> str:
    normalized = "large-v3-turbo" if model_name == "turbo" else model_name
    if normalized.startswith("ggml-") and normalized.endswith(".bin"):
        return normalized
    return f"ggml-{normalized}.bin"


def _build_prompt(*, hotwords: str | None, prompt_context: str | None) -> str | None:
    parts: list[str] = []
    if hotwords:
        parts.append(f"Technical terms and names: {hotwords}.")
    if prompt_context:
        parts.append(prompt_context)
    if not parts:
        return None
    return " ".join(parts)


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
    return max(30, min(300, int(duration * 20) + 20))


def _configured_port() -> int:
    configured = os.environ.get("DICTATE_WHISPER_CPP_PORT")
    if configured:
        return int(configured)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(*, port: int, process: subprocess.Popen[bytes], timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"whisper.cpp server exited with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1.0):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    raise RuntimeError("timed out waiting for whisper.cpp server to start")


def _post_multipart(
    *,
    url: str,
    file_path: Path,
    fields: dict[str, str],
    timeout: int,
) -> str:
    boundary = f"----dictate-{os.getpid()}-{time.time_ns()}"
    body = bytearray()
    for name, value in fields.items():
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
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"whisper.cpp server returned HTTP {exc.code}: {detail}") from exc


def _extract_text(response: str) -> str:
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return response.strip()

    text = data.get("text")
    if isinstance(text, str):
        return text.strip()

    transcription = data.get("transcription")
    if isinstance(transcription, list):
        parts = [item.get("text", "") for item in transcription if isinstance(item, dict)]
        return " ".join(part.strip() for part in parts if part.strip()).strip()

    return response.strip()
