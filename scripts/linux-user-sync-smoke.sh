#!/usr/bin/env bash
# Linux user-install smoke for the Dictate Pro encrypted sync path.
#
# This intentionally runs through install.sh and the installed Python entrypoint
# in an isolated HOME. It does not contact production: a fake Pro gateway is
# injected into the UI backend so the smoke can verify the packaged app's local
# sync behavior without secrets or network access.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_RUNTIME_DIR="$TMP/runtime"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_RUNTIME_DIR"

echo "==> Installing Dictate into isolated Linux user home"
"$ROOT/install.sh" --user --no-ui --no-startup --no-prepare-turbo --no-verify --session-backend x11

PYTHON="$HOME/.local/share/dictate/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Installed Python not found: $PYTHON"
  exit 1
fi

echo "==> Running installed encrypted-sync smoke"
"$PYTHON" <<'PY'
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from dictate.api_keys import ApiKeyStatus
from dictate.history import HistoryStore
from dictate.note_store import NoteStore
from dictate.pro.client import ProSession
from dictate.sync import SyncSettingsStore, generate_device_key_pair
from dictate.ui_server import EventBroker, UiBackend, UiPrefsStore, serve

base = Path(os.environ["HOME"]) / "dictate-sync-smoke"
base.mkdir(parents=True, exist_ok=True)
secret_keys: dict[str, str] = {}


class FakeProClient:
    def __init__(self) -> None:
        self.keys = generate_device_key_pair()
        self.session = ProSession(
            account_id="acct_linux_smoke",
            device_id="device_linux_smoke",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        self.cloud: list[dict] = []
        self.saved_key_envelopes: list[dict] = []
        self.fail_push = False
        self.cursor_updates: list[int] = []

    def get_state(self) -> dict:
        return {
            "signedIn": True,
            "entitlements": {"active": True, "features": ["sync"]},
            "usage": {"sync": {"record_count": len(self.cloud)}},
            "account": {"account_id": self.session.account_id},
            "commerce": {"subscriptions": []},
        }

    def refresh_if_needed(self) -> ProSession:
        return self.session

    def list_devices(self) -> dict:
        return {
            "devices": [
                {
                    "device_id": self.session.device_id,
                    "label": "Linux smoke",
                    "public_key": self.keys.public_key,
                    "trusted_at": "2026-07-05T12:00:00+00:00",
                    "revoked_at": None,
                }
            ]
        }

    def save_key_envelope(self, *, envelope_kind: str, envelope: dict) -> dict:
        saved = {"envelope_kind": envelope_kind, "envelope": envelope}
        self.saved_key_envelopes.append(saved)
        return saved

    def list_key_envelopes(self, *, envelope_kind: str | None = None) -> dict:
        return {
            "envelopes": [
                item for item in self.saved_key_envelopes
                if envelope_kind is None or item["envelope_kind"] == envelope_kind
            ]
        }

    def drain_sync_outbox(self, outbox) -> dict:  # noqa: ANN001
        if self.fail_push:
            raise RuntimeError("simulated offline gateway")
        pending = outbox.pending()
        for record in pending:
            self.cloud.append({**asdict(record), "seq": len(self.cloud) + 1})
        outbox.replace_pending([])
        return {"pushed": len(pending), "remaining": 0, "results": []}

    def get_sync_changes(self, *, since: int = 0, limit: int = 500) -> dict:
        records = [record for record in self.cloud if int(record["seq"]) > since][:limit]
        return {
            "records": records,
            "next_seq": records[-1]["seq"] if records else since,
            "has_more": len(records) >= limit,
        }

    def update_sync_cursor(self, *, last_seq: int) -> dict:
        self.cursor_updates.append(last_seq)
        return {"last_seq": last_seq}


def request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - loopback smoke
        return json.loads(resp.read().decode("utf-8"))


fake = FakeProClient()
sync_settings = SyncSettingsStore(
    path=base / "sync-state.json",
    device_path=base / "sync-device.json",
    outbox_path=base / "sync-outbox.jsonl",
    save_key=lambda account, key: secret_keys.__setitem__(account, key),
    read_key=lambda account: secret_keys.get(account),
    clear_key=lambda account: secret_keys.pop(account, None),
)
backend = UiBackend(
    config_path=base / "config.yaml",
    history_store=HistoryStore(base / "recent-history.json"),
    note_store=NoteStore(base / "notes"),
    prefs_store=UiPrefsStore(base / "ui-prefs.json"),
    sync_settings=sync_settings,
    pro_client=fake,
    broker=EventBroker(),
    save_api_key=lambda backend, key: None,
    clear_api_key=lambda backend: None,
    api_key_status=lambda backend, **kw: ApiKeyStatus(backend=backend, status="None"),
    validate_api_key_format=lambda backend, key: None,
    secret_store_description=lambda: "isolated smoke secret store",
    secret_store_available=lambda: True,
    startup_enabled=lambda: False,
    set_startup_enabled=lambda enabled: None,
)
backend.history_store.append("linux packaged sync smoke initial private text")
handle = serve(backend=backend, token="linux-smoke-token", write_handshake=False)
try:
    enabled = request("POST", f"{handle.url}/api/pro/sync/enable", "linux-smoke-token", {})
    if not enabled["sync"]["enabled"] or not enabled.get("recoveryKey"):
        raise AssertionError(f"sync enable did not return enabled state and recovery key: {enabled}")
    if not fake.cloud:
        raise AssertionError("initial sync did not push the existing local history snapshot")
    cloud_json = json.dumps(fake.cloud)
    if "linux packaged sync smoke initial private text" in cloud_json:
        raise AssertionError("plaintext history text leaked into cloud sync records")

    fake.fail_push = True
    backend.history_store.append("linux packaged sync smoke offline private text")
    offline = request("POST", f"{handle.url}/api/pro/sync/run", "linux-smoke-token", {})
    if "sync push failed" not in str(offline["result"].get("error")):
        raise AssertionError(f"offline sync did not report a push failure: {offline}")
    pending = sync_settings.outbox().pending()
    if not pending:
        raise AssertionError("offline sync did not keep encrypted outbox records pending")

    fake.fail_push = False
    recovered = request("POST", f"{handle.url}/api/pro/sync/run", "linux-smoke-token", {})
    if recovered["result"].get("error"):
        raise AssertionError(f"recovered sync still failed: {recovered}")
    if sync_settings.outbox().pending():
        raise AssertionError("recovered sync did not drain pending encrypted records")
    cloud_json = json.dumps(fake.cloud)
    if "linux packaged sync smoke offline private text" in cloud_json:
        raise AssertionError("plaintext offline history text leaked into cloud sync records")

    exported = request("GET", f"{handle.url}/api/local/export", "linux-smoke-token")
    exported_json = json.dumps(exported)
    if "linux packaged sync smoke offline private text" not in exported_json:
        raise AssertionError("local export did not include local history")
    if "sync_records" in exported_json or "refresh" in exported_json:
        raise AssertionError("local export included cloud sync state or token-like data")
finally:
    handle.shutdown()

print("Dictate Linux user encrypted-sync smoke passed.")
PY
