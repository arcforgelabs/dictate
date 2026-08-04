"""Frozen-contract tests for managed hosted-result encryption and key lifecycle."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from dictate.pro.hosted_result import (
    CONTRACT_VERSION,
    CRYPTO_FORMAT,
    ExpectedHostedResult,
    HostedResultError,
    HostedResultKeyStore,
    HostedResultPendingStore,
    decrypt_hosted_result,
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _vector() -> tuple[dict[str, object], ExpectedHostedResult, str, dict[str, object]]:
    recipient_private = X25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    recipient_public = recipient_private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    ephemeral = X25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    expected = ExpectedHostedResult(
        account_id="account_1",
        device_id="device_1",
        job_id="job_1",
        request_id="request_1",
        correlation_id="correlation_1",
        artifact_id="artifact_1",
    )
    key_id = "recipient_1"
    key_version = 3
    aad = {
        "contract_version": CONTRACT_VERSION,
        "crypto_format": CRYPTO_FORMAT,
        "account_id": expected.account_id,
        "device_id": expected.device_id,
        "job_id": expected.job_id,
        "request_id": expected.request_id,
        "correlation_id": expected.correlation_id,
        "artifact_id": expected.artifact_id,
        "recipient_key_id": key_id,
        "recipient_key_version": str(key_version),
        "ephemeral_public_key": _b64(ephemeral_public),
    }
    aad_bytes = json.dumps(aad, sort_keys=True, separators=(",", ":")).encode()
    salt = bytes(range(65, 97))
    nonce = bytes(range(97, 109))
    kdf_info = (
        f"dictate-result|{CONTRACT_VERSION}|{CRYPTO_FORMAT}|{expected.artifact_id}|{key_id}|{key_version}"
    )
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(recipient_public))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=kdf_info.encode()).derive(shared)
    plaintext = {"text": "private transcript", "segments": [{"start": 0.0, "end": 1.0}]}
    ciphertext = AESGCM(key).encrypt(
        nonce,
        json.dumps(plaintext, sort_keys=True, separators=(",", ":")).encode(),
        aad_bytes,
    )
    envelope: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "crypto_format": CRYPTO_FORMAT,
        "crypto_version": 1,
        "algorithm": "X25519+AES-256-GCM",
        "kdf": "HKDF-SHA256",
        "kdf_salt": _b64(salt),
        "kdf_info": kdf_info,
        "ephemeral_public_key": _b64(ephemeral_public),
        "nonce": _b64(nonce),
        "aad": aad,
        "ciphertext": _b64(ciphertext),
        "integrity_binding": _b64(hashlib.sha256(aad_bytes).digest()),
        "recipient_key_id": key_id,
        "recipient_key_version": key_version,
        "job_id": expected.job_id,
        "request_id": expected.request_id,
        "correlation_id": expected.correlation_id,
        "artifact_id": expected.artifact_id,
        "expires_at": "2099-07-19T00:00:00+00:00",
        "ack_state": "pending",
    }
    private = recipient_private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return envelope, expected, _b64(private), plaintext


class HostedResultEnvelopeTests(unittest.TestCase):
    def test_decrypts_frozen_deterministic_vector(self) -> None:
        envelope, expected, private_key, plaintext = _vector()
        self.assertEqual(decrypt_hosted_result(envelope, expected=expected, private_key=private_key), plaintext)

    def test_refetching_identical_envelope_is_stable(self) -> None:
        envelope, expected, private_key, plaintext = _vector()
        encoded_before = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(decrypt_hosted_result(copy.deepcopy(envelope), expected=expected, private_key=private_key), plaintext)
        self.assertEqual(decrypt_hosted_result(copy.deepcopy(envelope), expected=expected, private_key=private_key), plaintext)
        self.assertEqual(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(), encoded_before)

    def test_rejects_every_wrong_expected_identity(self) -> None:
        envelope, expected, private_key, _plaintext = _vector()
        for field in ("account_id", "device_id", "job_id", "request_id", "correlation_id", "artifact_id"):
            values = {
                "account_id": expected.account_id,
                "device_id": expected.device_id,
                "job_id": expected.job_id,
                "request_id": expected.request_id,
                "correlation_id": expected.correlation_id,
                "artifact_id": expected.artifact_id,
            }
            values[field] = f"wrong_{field}"
            with self.subTest(field=field), self.assertRaises(HostedResultError):
                decrypt_hosted_result(
                    envelope,
                    expected=ExpectedHostedResult(**values),
                    private_key=private_key,
                )

    def test_rejects_tampered_aad_ciphertext_and_key(self) -> None:
        envelope, expected, private_key, _plaintext = _vector()
        mutations = []
        wrong_aad = copy.deepcopy(envelope)
        wrong_aad["aad"]["device_id"] = "device_2"  # type: ignore[index]
        mutations.append((wrong_aad, private_key))
        wrong_ciphertext = copy.deepcopy(envelope)
        wrong_ciphertext["ciphertext"] = str(wrong_ciphertext["ciphertext"])[:-1] + "A"
        mutations.append((wrong_ciphertext, private_key))
        mutations.append((envelope, _b64(bytes(range(100, 132)))))
        for candidate, key in mutations:
            with self.subTest(candidate=candidate), self.assertRaises(HostedResultError):
                decrypt_hosted_result(candidate, expected=expected, private_key=key)

    def test_rejects_extra_fields_and_noncanonical_base64(self) -> None:
        envelope, expected, private_key, _plaintext = _vector()
        extra = copy.deepcopy(envelope)
        extra["plaintext"] = "must never be accepted"
        with self.assertRaises(HostedResultError):
            decrypt_hosted_result(extra, expected=expected, private_key=private_key)
        padded = copy.deepcopy(envelope)
        padded["nonce"] = str(padded["nonce"]) + "="
        with self.assertRaises(HostedResultError):
            decrypt_hosted_result(padded, expected=expected, private_key=private_key)

    def test_rejects_expired_artifact(self) -> None:
        envelope, expected, private_key, _plaintext = _vector()
        envelope["expires_at"] = "2020-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(HostedResultError, "expired"):
            decrypt_hosted_result(envelope, expected=expected, private_key=private_key)


class HostedResultKeyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.secrets: dict[tuple[str, int], str] = {}
        self.purged: list[tuple[str, int]] = []
        self.store = HostedResultKeyStore(
            path=Path(self.tmp.name) / "hosted-result-keys.json",
            save_secret=lambda key_id, version, value: self.secrets.__setitem__(
                (key_id, version), value
            ),
            read_secret=lambda key_id, version: self.secrets.get((key_id, version)),
            clear_secret=lambda key_id, version: self.secrets.pop((key_id, version), None),
            purge_pending=lambda key_id, version: self.purged.append((key_id, version)),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_rotation_preserves_old_key_as_decrypt_only(self) -> None:
        first = self.store.create_or_rotate()
        second = self.store.create_or_rotate()
        keys = self.store.list()
        self.assertEqual([(key.version, key.status) for key in keys], [(1, "decrypt_only"), (2, "active")])
        self.assertEqual(self.store.resolve(first.recipient_key_id, first.version)[0].status, "decrypt_only")
        self.assertEqual(self.store.active(), second)

    def test_revocation_removes_secret_and_denies_decryption(self) -> None:
        key = self.store.create_or_rotate()
        self.store.revoke(key.recipient_key_id, key.version)
        self.assertNotIn((key.recipient_key_id, key.version), self.secrets)
        self.assertEqual(self.purged, [(key.recipient_key_id, key.version)])
        with self.assertRaisesRegex(HostedResultError, "revoked"):
            self.store.resolve(key.recipient_key_id, key.version)

    def test_metadata_contains_no_private_key_and_is_private(self) -> None:
        key = self.store.create_or_rotate()
        text = self.store.path.read_text(encoding="utf-8")
        self.assertNotIn(self.secrets[(key.recipient_key_id, key.version)], text)
        if sys.platform.startswith("win"):
            # os.chmod only toggles the read-only bit on Windows, so the store's
            # chmod(0o600) cannot produce a POSIX mode there and st_mode reads
            # back as 0o666. Confidentiality comes from the user-profile ACL
            # instead. The leak assertion above is what matters and runs
            # everywhere; only the POSIX mode check is skipped.
            return
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)


class HostedResultPendingStoreTests(unittest.TestCase):
    def test_encrypted_artifact_survives_ack_until_explicit_application_acceptance(self) -> None:
        envelope, _expected, _private_key, plaintext = _vector()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pending.json"
            store = HostedResultPendingStore(path=path)
            store.put(
                job_id="job_1",
                request_id="request_1",
                correlation_id="correlation_1",
                envelope=envelope,
            )
            store.mark_acknowledged("job_1", "ack_1")
            replay = HostedResultPendingStore(path=path).get("job_1")
            self.assertTrue(replay["acknowledged"])
            self.assertEqual(replay["envelope"], envelope)
            self.assertNotIn(plaintext["text"], path.read_text(encoding="utf-8"))
            store.accept("job_1")
            self.assertIsNone(store.get("job_1"))

    def test_conflicting_refetch_cannot_replace_pending_encrypted_artifact(self) -> None:
        envelope, _expected, _private_key, _plaintext = _vector()
        with tempfile.TemporaryDirectory() as tmp:
            store = HostedResultPendingStore(path=Path(tmp) / "pending.json")
            store.put(
                job_id="job_1",
                request_id="request_1",
                correlation_id="correlation_1",
                envelope=envelope,
            )
            changed = copy.deepcopy(envelope)
            changed["ciphertext"] = str(changed["ciphertext"])[:-1] + "A"
            with self.assertRaisesRegex(HostedResultError, "conflicts"):
                store.put(
                    job_id="job_1",
                    request_id="request_1",
                    correlation_id="correlation_1",
                    envelope=changed,
                )

    def test_expiry_cleanup_is_bounded_by_authoritative_envelope_expiry(self) -> None:
        envelope, _expected, _private_key, _plaintext = _vector()
        expired = copy.deepcopy(envelope)
        expired["expires_at"] = "2026-07-18T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            store = HostedResultPendingStore(path=Path(tmp) / "pending.json")
            store.put(
                job_id="job_1",
                request_id="request_1",
                correlation_id="correlation_1",
                envelope=expired,
            )
            self.assertEqual(
                store.purge_expired(now=datetime(2026, 7, 17, tzinfo=timezone.utc)),
                0,
            )
            self.assertEqual(
                store.purge_expired(now=datetime(2026, 7, 19, tzinfo=timezone.utc)),
                1,
            )
            self.assertIsNone(store.get("job_1"))

    def test_key_revocation_purges_only_matching_recipient_version(self) -> None:
        envelope, _expected, _private_key, _plaintext = _vector()
        other = copy.deepcopy(envelope)
        other["recipient_key_version"] = 4
        with tempfile.TemporaryDirectory() as tmp:
            store = HostedResultPendingStore(path=Path(tmp) / "pending.json")
            store.put(
                job_id="job_1",
                request_id="request_1",
                correlation_id="correlation_1",
                envelope=envelope,
            )
            store.put(
                job_id="job_2",
                request_id="request_2",
                correlation_id="correlation_2",
                envelope=other,
            )
            store.purge_recipient("recipient_1", 3)
            self.assertIsNone(store.get("job_1"))
            self.assertIsNotNone(store.get("job_2"))


if __name__ == "__main__":
    unittest.main()
