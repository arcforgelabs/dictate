"""Server-side signatures for Dictate Pro sync metadata."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)


SIGNATURE_ALGORITHM = "Ed25519"


def canonical_metadata_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class MetadataSigner:
    def __init__(self, private_key: ed25519.Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self.key_id = self._key_id(self.public_key)

    @classmethod
    def load_or_create(cls, path: Path) -> "MetadataSigner":
        pem = os.environ.get("DICTATE_PRO_SERVER_SIGNING_KEY_PEM", "").strip()
        if pem:
            key = load_pem_private_key(pem.encode("utf-8"), password=None)
            if not isinstance(key, ed25519.Ed25519PrivateKey):
                raise ValueError("DICTATE_PRO_SERVER_SIGNING_KEY_PEM must contain an Ed25519 private key")
            return cls(key)

        if path.is_file():
            key = load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, ed25519.Ed25519PrivateKey):
                raise ValueError(f"server signing key is not Ed25519: {path}")
            return cls(key)

        path.parent.mkdir(parents=True, exist_ok=True)
        key = ed25519.Ed25519PrivateKey.generate()
        pem_bytes = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(pem_bytes)
            temp_name = handle.name
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        return cls(key)

    @property
    def public_key(self) -> str:
        raw = self._public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode("ascii")

    def sign(self, payload: dict[str, Any]) -> str:
        signature = self._private_key.sign(canonical_metadata_bytes(payload))
        return base64.b64encode(signature).decode("ascii")

    def bundle(self, payload: dict[str, Any]) -> dict[str, str]:
        return {
            "algorithm": SIGNATURE_ALGORITHM,
            "key_id": self.key_id,
            "public_key": self.public_key,
            "signature": self.sign(payload),
        }

    @staticmethod
    def _key_id(public_key: str) -> str:
        return "ed25519:" + hashlib.sha256(public_key.encode("ascii")).hexdigest()[:16]


def verify_metadata_signature(payload: dict[str, Any], bundle: dict[str, str]) -> bool:
    if bundle.get("algorithm") != SIGNATURE_ALGORITHM:
        return False
    public_key = str(bundle.get("public_key") or "")
    signature = str(bundle.get("signature") or "")
    if not public_key or not signature:
        return False
    try:
        verifier = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key))
        verifier.verify(base64.b64decode(signature), canonical_metadata_bytes(payload))
    except (ValueError, InvalidSignature):
        return False
    return True
