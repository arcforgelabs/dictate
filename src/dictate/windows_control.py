"""Windows-friendly control panel for headless Dictate installs."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from dictate.api_keys import API_BACKENDS, ApiKeyStorageError, api_key_status, save_api_key
from dictate.config import (
    CONFIG_PATH,
    load_config,
    set_push_to_talk_combo,
    set_stt_runtime_profile,
    set_stt_selection,
)
from dictate.history import HISTORY_PATH, HistoryEntry, HistoryStore
from dictate.hotkey import HotkeyParseError, format_hotkey_combo, normalize_push_to_talk_combo
from dictate.outputs import ClipboardOutput, OutputError
from dictate.stt import BACKEND_REGISTRY

BACKEND_CHOICES = ("faster-whisper", "openai", "xai", "gemini")
DEFAULT_BACKEND = "faster-whisper"
MODEL_CHOICES = {
    backend: spec.model_examples for backend, spec in BACKEND_REGISTRY.items()
}
DEFAULT_MODELS = {
    "faster-whisper": "turbo",
    "openai": "gpt-4o-mini-transcribe",
    "xai": "grok-speech-to-text",
    "gemini": "gemini-3-flash-preview",
}
LOCAL_RUNTIME_CHOICES = ("CPU", "GPU")
HISTORY_PAGE_SIZE = 5


def run_control_panel() -> int:
    root = tk.Tk()
    ControlPanel(root)
    root.mainloop()
    return 0


class ControlPanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Dictate Controls")
        self.root.minsize(760, 560)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(1500, lambda: self.root.attributes("-topmost", False))

        self.status_var = tk.StringVar(value="")
        self.backend_var = tk.StringVar(value=DEFAULT_BACKEND)
        self.model_var = tk.StringVar(value=DEFAULT_MODELS[DEFAULT_BACKEND])
        self.device_var = tk.StringVar(value="cpu")
        self.compute_var = tk.StringVar(value="int8")
        self.local_runtime_var = tk.StringVar(value="CPU")
        self.combo_var = tk.StringVar(value="ctrl_r")
        self.api_key_var = tk.StringVar(value="")
        self.api_status_var = tk.StringVar(value="API key: None")
        self.history_page_var = tk.StringVar(value="")
        self._history_page = 0
        self._history_entries: list[HistoryEntry] = []
        self.model_box: ttk.Combobox | None = None
        self.api_entry: ttk.Entry | None = None

        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        status = ttk.Label(outer, textvariable=self.status_var, justify=tk.LEFT)
        status.grid(row=0, column=0, sticky="ew")

        config_frame = ttk.LabelFrame(outer, text="Configuration", padding=10)
        config_frame.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        for idx in range(4):
            config_frame.columnconfigure(idx, weight=1)

        ttk.Label(config_frame, text="Provider").grid(row=0, column=0, sticky="w")
        backend_box = ttk.Combobox(
            config_frame,
            textvariable=self.backend_var,
            values=BACKEND_CHOICES,
            state="readonly",
        )
        backend_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        backend_box.bind("<<ComboboxSelected>>", lambda _event: self._on_backend_changed())

        ttk.Label(config_frame, text="Select Model").grid(row=0, column=1, sticky="w")
        self.model_box = ttk.Combobox(
            config_frame,
            textvariable=self.model_var,
            state="readonly",
        )
        self.model_box.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        self.model_box.bind("<<ComboboxSelected>>", lambda _event: self._sync_status_line())

        ttk.Label(config_frame, text="API key").grid(row=0, column=2, sticky="w")
        self.api_entry = ttk.Entry(config_frame, textvariable=self.api_key_var, show="*")
        self.api_entry.grid(row=1, column=2, sticky="ew", padx=(0, 8))
        ttk.Label(config_frame, textvariable=self.api_status_var).grid(
            row=2,
            column=2,
            sticky="w",
            padx=(0, 8),
            pady=(4, 0),
        )

        ttk.Label(config_frame, text="Hotkeys").grid(row=0, column=3, sticky="w")
        combo_entry = ttk.Entry(config_frame, textvariable=self.combo_var)
        combo_entry.grid(row=1, column=3, sticky="ew")

        advanced_frame = ttk.Frame(config_frame)
        advanced_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        advanced_frame.columnconfigure(0, weight=1)
        advanced_frame.columnconfigure(1, weight=1)

        ttk.Label(advanced_frame, text="Local").grid(row=0, column=0, sticky="w")
        runtime_box = ttk.Combobox(
            advanced_frame,
            textvariable=self.local_runtime_var,
            values=LOCAL_RUNTIME_CHOICES,
            state="readonly",
        )
        runtime_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        runtime_box.bind("<<ComboboxSelected>>", lambda _event: self._on_runtime_changed())

        button_frame = ttk.Frame(config_frame)
        button_frame.grid(row=4, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(button_frame, text="Save", command=self.save).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            button_frame,
            text="Save & Restart Dictate",
            command=self.save_and_restart,
        ).pack(side=tk.LEFT)

        history_frame = ttk.LabelFrame(outer, text="Recent History", padding=10)
        history_frame.grid(row=2, column=0, sticky="nsew")
        history_frame.columnconfigure(0, weight=1)
        history_frame.rowconfigure(0, weight=1)

        self.history_rows = ttk.Frame(history_frame)
        self.history_rows.grid(row=0, column=0, sticky="nsew")
        self.history_rows.columnconfigure(0, weight=1)

        history_controls = ttk.Frame(history_frame)
        history_controls.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        history_controls.columnconfigure(1, weight=1)
        ttk.Button(history_controls, text="Previous", command=self.previous_history_page).grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Label(history_controls, textvariable=self.history_page_var, anchor=tk.CENTER).grid(
            row=0,
            column=1,
            sticky="ew",
        )
        ttk.Button(history_controls, text="Next", command=self.next_history_page).grid(
            row=0,
            column=2,
            sticky="e",
        )

        ttk.Button(history_frame, text="Refresh History", command=self.refresh_history).grid(
            row=2,
            column=0,
            sticky="e",
            pady=(6, 0),
        )

    def refresh(self) -> None:
        config = load_config()
        backend = config.stt_backend if config.stt_backend in BACKEND_CHOICES else DEFAULT_BACKEND
        self.backend_var.set(backend)
        self._sync_model_choices()
        model_choices = MODEL_CHOICES[backend]
        default_model = DEFAULT_MODELS.get(backend, model_choices[0])
        self.model_var.set(config.stt_model if config.stt_model in model_choices else default_model)
        self._set_local_runtime_from_config(config.stt_device, config.stt_compute_type)
        self.api_key_var.set("")
        combo = config.push_to_talk_combo or config.push_to_talk_key or "ctrl_r"
        self.combo_var.set(combo)
        self._sync_api_key_field()
        self._sync_status_line()
        self.refresh_history()

    def _on_backend_changed(self) -> None:
        self._sync_model_choices()
        self.api_key_var.set("")
        self._sync_api_key_field()
        self._sync_status_line()

    def _on_runtime_changed(self) -> None:
        if self.local_runtime_var.get() == "GPU":
            self.device_var.set("cuda")
            self.compute_var.set("int8")
        else:
            self.device_var.set("cpu")
            self.compute_var.set("int8")
        self._sync_status_line()

    def _sync_model_choices(self) -> None:
        backend = self.backend_var.get()
        choices = MODEL_CHOICES.get(backend, MODEL_CHOICES[DEFAULT_BACKEND])
        if self.model_box is not None:
            self.model_box.configure(values=choices)
        if self.model_var.get() not in choices:
            self.model_var.set(DEFAULT_MODELS.get(backend, choices[0]))

    def _sync_api_key_field(self) -> None:
        if self.api_entry is None:
            return
        backend = self.backend_var.get()
        state = tk.NORMAL if backend in API_BACKENDS else tk.DISABLED
        self.api_entry.configure(state=state)
        if backend in API_BACKENDS:
            _apply_api_key_command_from_config(backend)
            self.api_status_var.set(f"API key: {api_key_status(backend).status}")
        else:
            self.api_status_var.set("API key: Local")

    def _set_local_runtime_from_config(
        self,
        device: str | None,
        compute_type: str | None,
    ) -> None:
        if device == "cuda":
            self.local_runtime_var.set("GPU")
            self.device_var.set("cuda")
            self.compute_var.set(compute_type if compute_type in {"int8", "float16"} else "int8")
            return
        self.local_runtime_var.set("CPU")
        self.device_var.set("cpu")
        self.compute_var.set("int8")

    def _sync_status_line(self) -> None:
        backend = self.backend_var.get()
        model = self.model_var.get()
        if backend == "faster-whisper":
            selected = f"Selected: Local / {model} ({self.local_runtime_var.get()})"
        else:
            selected = f"Selected: {backend} / {model}"
        self.status_var.set(
            f"{selected}\nConfig: {CONFIG_PATH}\nHistory: {HISTORY_PATH}\n"
            "Changes apply after restart. Use Save & Restart Dictate to apply immediately."
        )

    def refresh_history(self) -> None:
        self._history_entries = HistoryStore().load()
        max_page = max(0, (len(self._history_entries) - 1) // HISTORY_PAGE_SIZE)
        self._history_page = min(self._history_page, max_page)
        self._render_history_page()

    def _render_history_page(self) -> None:
        for child in self.history_rows.winfo_children():
            child.destroy()

        entries = self._history_entries
        if not entries:
            self.history_page_var.set("No history")
            ttk.Label(self.history_rows, text="No recent dictations yet.").grid(
                row=0,
                column=0,
                sticky="w",
            )
            return

        max_page = (len(entries) - 1) // HISTORY_PAGE_SIZE
        self.history_page_var.set(
            f"Page {self._history_page + 1} of {max_page + 1} ({len(entries)} entries)"
        )
        start = self._history_page * HISTORY_PAGE_SIZE
        page_entries = entries[start : start + HISTORY_PAGE_SIZE]
        for idx, entry in enumerate(page_entries):
            self._add_history_row(idx, entry)

    def previous_history_page(self) -> None:
        if self._history_page > 0:
            self._history_page -= 1
            self._render_history_page()

    def next_history_page(self) -> None:
        if not self._history_entries:
            return
        max_page = (len(self._history_entries) - 1) // HISTORY_PAGE_SIZE
        if self._history_page < max_page:
            self._history_page += 1
            self._render_history_page()

    def _add_history_row(self, idx: int, entry: HistoryEntry) -> None:
        row = ttk.Frame(self.history_rows, padding=(0, 0, 0, 8))
        row.grid(row=idx, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)

        label = ttk.Label(row, text=_format_timestamp(entry.created_at))
        label.grid(row=0, column=0, sticky="w")

        text = tk.Text(row, height=3, wrap=tk.WORD)
        text.insert("1.0", entry.text)
        text.configure(state=tk.DISABLED)
        text.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ttk.Button(row, text="Copy", command=lambda item=entry: self.copy_entry(item)).grid(
            row=1,
            column=1,
            sticky="n",
        )

    def save(self) -> bool:
        backend = self.backend_var.get()
        model = self.model_var.get()
        device = self.device_var.get()
        compute_type = self.compute_var.get()
        combo = self.combo_var.get().strip()
        try:
            normalized_combo = normalize_push_to_talk_combo(combo)
        except HotkeyParseError as exc:
            messagebox.showerror("Invalid Hotkey", str(exc))
            return False

        api_key = self.api_key_var.get().strip()
        if backend in API_BACKENDS:
            _apply_api_key_command_from_config(backend)
            status = (
                api_key_status(backend, api_key=api_key, validate_remote=True)
                if api_key
                else api_key_status(backend, validate_remote=True)
            )
            if not status.ready:
                messagebox.showerror(
                    "API Key Required",
                    f"{backend} API key status: {status.status}. "
                    "Add a valid key before saving this model.",
                )
                return False
            if api_key:
                try:
                    save_api_key(backend, api_key)
                except ApiKeyStorageError as exc:
                    messagebox.showerror("API Key Not Saved", str(exc))
                    return False
                self.api_key_var.set("")
                self._sync_api_key_field()
        set_stt_selection(backend, model)
        set_stt_runtime_profile(device, compute_type)
        set_push_to_talk_combo(normalized_combo)
        self.combo_var.set(normalized_combo)
        self._sync_status_line()
        messagebox.showinfo(
            "Saved",
            f"Saved configuration.\nHotkey: {format_hotkey_combo(normalized_combo)}",
        )
        return True

    def save_and_restart(self) -> None:
        if not self.save():
            return
        try:
            _restart_daemon()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Restart Failed", str(exc))
            return
        messagebox.showinfo("Restarted", "Dictate restarted with the saved configuration.")

    def copy_entry(self, entry: HistoryEntry) -> None:
        try:
            ClipboardOutput().send(entry.text)
        except OutputError as exc:
            messagebox.showerror("Copy Failed", str(exc))
            return
        messagebox.showinfo("Copied", "Copied dictation text to clipboard.")


def _format_timestamp(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return iso_str


def _apply_api_key_command_from_config(backend: str) -> None:
    config = load_config()
    if backend == "openai" and config.openai_api_key_command:
        os.environ.setdefault("DICTATE_OPENAI_API_KEY_COMMAND", config.openai_api_key_command)
    if backend == "xai" and config.xai_api_key_command:
        os.environ.setdefault("DICTATE_XAI_API_KEY_COMMAND", config.xai_api_key_command)
    if backend == "gemini" and config.gemini_api_key_command:
        os.environ.setdefault("DICTATE_GEMINI_API_KEY_COMMAND", config.gemini_api_key_command)


def _restart_daemon() -> None:
    scripts_dir = Path(sys.executable).resolve().parent
    launcher = scripts_dir / "dictate-daemon.cmd"
    if not launcher.is_file():
        raise RuntimeError(f"Daemon launcher not found: {launcher}")

    stop_script = r"""
$matches = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -like '*dictate.exe* --no-tray*' -or
        $_.CommandLine -like '*dictate-daemon.cmd*'
    }
foreach ($match in $matches) {
    if ($match.ProcessId -ne $PID) {
        Stop-Process -Id $match.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", stop_script],
        check=True,
    )
    subprocess.Popen(
        [str(launcher)],
        cwd=str(scripts_dir.parents[1]),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
