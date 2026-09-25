# Security Policy

If you believe you found a security issue in Dictate, report it privately first.

Use GitHub private vulnerability reporting for this repository when it is available. If private reporting is not available, open a public issue that only asks for a disclosure contact and does not include exploit details, secrets, API keys, logs containing credentials, or private user vocabulary.

## What to Include

- Dictate version and commit SHA when possible.
- Operating system and install path.
- Reproduction steps against the latest release or current `master`.
- The impact and why it crosses a real security boundary.
- A focused fix or mitigation if you have one.

## Do Not Post Publicly

- Provider API keys or credential material.
- Personal hotwords, private names, customer terms, or sensitive dictation text.
- Full logs unless you have checked and removed secrets.
- Exploit details for an unpatched issue.

Dictate is a local desktop app. A trusted local user intentionally installing, configuring, or running local commands is usually not a vulnerability by itself. Reports are most useful when they show an unintended path from untrusted input to credential exposure, command execution, data exposure, privilege escalation, or update/install compromise.

## Accepted Risks (tracked)

These advisories are accepted for now. They share a common cause: they all come
from the optional `[whisperx]` extra's pinned dependency stack, none of them are
shipped in the release artifact, and none are reachable from untrusted input in
how Dictate uses them.

Why they cannot simply be upgraded: **whisperx 3.8.6 (the latest published
release) pins `torch~=2.8.0` and `huggingface-hub<1.0.0`.** Those pins cap the
whole resolution — torch cannot move to a patched 2.9+/2.12+, and transformers
cannot move to the patched 5.x line (transformers 5 requires
`huggingface-hub>=1.0.0`). whisperx is a needed, in-progress feature, so we keep
it rather than drop it to force the upgrades.

Common mitigating facts for all entries below:
- `[whisperx]` (and `[gpu]`) are **not** in the shipped `.deb`/AppImage, which is
  frozen from `[x11,wayland]`; the default product uses faster-whisper
  (CTranslate2), which pulls none of these packages.
- Dictate is a local app processing the user's own audio — there is no untrusted
  remote input feeding these libraries.

Advisories:

- **torch memory corruption** — GHSA-vgrw-7cvw-pwgx (medium, fix 2.9.1),
  GHSA-qfhq-4f3w-5fph (low, fix 2.10.0), GHSA-rrmf-rvhw-rf47 (low).
  In `torch.lstm_cell` / `torch.jit.script` / `unpack_sequence`. Blocked at
  torch 2.8.x by whisperx's `torch~=2.8.0` pin.
- **transformers `Trainer` RCE** — GHSA-69w3-r845-3855 (medium, fix 5.x).
  Reachable only via the `Trainer` (training) class; Dictate only runs inference
  and never trains. Blocked below 5.x by whisperx's `huggingface-hub<1.0.0` pin.
- **nltk path traversal in `nltk.data.load()`** — GHSA-p4gq-832x-fm9v (high).
  This older advisory is not among the current open Dependabot alerts. The
  optional WhisperX stack now locks NLTK 3.10.3; do not treat the old
  `<= 3.9.4` version statement as current.
- **nltk model-artifact path sandbox bypass** — GHSA-8mgp-746c-j5xp (high).
  NLTK 3.10.3 is still affected, and GitHub lists no patched release.
  Transitive via the optional WhisperX stack. Dictate does not call the
  affected model-artifact APIs directly, but optional model paths still need
  evaluation against untrusted artifacts.

**Action:** when whisperx publishes a release that lifts its `torch` /
`huggingface-hub` pins, bump it, re-pin torch (`>=2.12.1`) and transformers
(`>=5.x`) and re-lock. Upgrade NLTK again when the outstanding advisory has
a patched release; remove entries here only after verifying the affected paths.
