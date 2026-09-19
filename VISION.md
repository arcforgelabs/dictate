# Dictate — Vision

Dictate turns speech into text on your own machine, and types it into whatever
app you are already using. Press a shortcut, speak, get text. That is the whole
product.

## Local only

Transcription runs on the user's machine. There is no account, no subscription,
no API key, no hosted model, and no network call in the transcription path.
Nothing the user says leaves the device.

This is a constraint, not a default. "Local-first with a cloud option" is not
what this is — a cloud option brings back accounts, keys, quotas, outage
handling and a privacy story that has to be argued rather than stated. The
value here is that none of that exists.

## What finished looks like

A user installs one package and it works. They do not assemble a UI, fetch a
model, wire a runtime, or read a setup guide to get their first sentence typed.

The honest gap today is packaging, not capability: the local transcription path
already works, and the effort is in shipping it as something pleasant to install
and run.

## What this is not

Not a meeting recorder, not a notes product, not a transcription service with a
desktop client. It does not compete with Whisper Flow or Granola and should not
grow in that direction. Speak, get accurate text, decide where it goes.

## Status

Dictate is not a commercial product. It was retired as one on 2026-08-25 and is
now worked on when there is time. Features are judged by whether they make local
dictation better, not by whether they would sell.

The account, subscription, cloud sync and hosted-transcription code is being
removed rather than maintained. See `docs/local-only-audit.md`.

---

This file is repository truth. Product direction is decided here and in GitHub
issues; earlier revisions of this file were snapshots of an external Confluence
page, which is no longer authoritative.
