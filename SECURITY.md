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

- Credential material, such as a Hugging Face token.
- Personal hotwords, private names, customer terms, or sensitive dictation text.
- Full logs unless you have checked and removed secrets.
- Exploit details for an unpatched issue.

Dictate is a local desktop app. A trusted local user intentionally installing, configuring, or running local commands is usually not a vulnerability by itself. Reports are most useful when they show an unintended path from untrusted input to credential exposure, command execution, data exposure, privilege escalation, or update/install compromise.

## Accepted Risks (tracked)

The WhisperX stack, whose `torch~=2.8` and `huggingface-hub<1` pins held back
torch, transformers and NLTK, was removed along with the other Whisper backends.
The locked torch is 2.14, which carries the fixes for GHSA-vgrw-7cvw-pwgx and
GHSA-qfhq-4f3w-5fph, and NLTK is no longer a dependency. One advisory remains:

- **transformers `Trainer` RCE** — GHSA-69w3-r845-3855 (medium, fix 5.x).
  transformers is pulled in only by the experimental `[sortformer]` Meeting
  extra, which pins it below 5.x because NeMo 2.6's ASR imports need the older
  tokenizer API. `[sortformer]` is **not** in the shipped `.deb`/AppImage/MSI,
  which are frozen from `[x11,wayland,meeting]` (`packaging/build-engine.sh`).
  The advisory is reachable only through the `Trainer` (training) class;
  Dictate only runs inference and never trains.

**Action:** when NeMo supports transformers 5.x, lift the `[sortformer]` pins
and re-lock, then remove this entry.
