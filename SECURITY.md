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

These known advisories are accepted for now because no fix is available and the
vulnerable code is not reachable in Dictate's usage. Revisit when upstream ships
a patched release.

- **nltk path traversal in `nltk.data.load()`** — GHSA-p4gq-832x-fm9v (HIGH).
  No patched release exists (advisory covers `<= 3.9.4`, the current latest).
  `nltk` is only a transitive dependency of the optional `[whisperx]` extra
  (`nltk` ← `whisperx`); it is **not** included in the shipped `.deb` (frozen
  from `[x11,wayland]`) and the default faster-whisper path never installs it.
  Dictate never calls `nltk` directly, and whisperx's internal use loads fixed
  resources rather than user-controlled URL-encoded paths, so the traversal sink
  is not reachable from untrusted input. **Action:** pin `nltk` to the first
  patched version once released, and remove this note.
