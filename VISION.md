# Dictate — Vision

Dictate turns speech into text on your own machine. Nothing you say leaves it.

Its job is dictation: press a shortcut, speak, and the text is typed into
whatever app you are already using. It can also take a longer note: keep
talking, and the text is saved to history to copy or export. That is the whole
product, voice to text locally, and nothing else.

Install and usage: [`README.md`](README.md). How to contribute:
[`CONTRIBUTING.md`](CONTRIBUTING.md). Reporting a security problem:
[`SECURITY.md`](SECURITY.md).

## Local only

Transcription runs on the user's machine. There is no account, no subscription,
no API key, no hosted model, and no network call in the transcription path.
Audio and transcripts never leave the device, and Dictate sends no telemetry,
analytics or crash reports. Its own logs do not record what was said.

This is a constraint, not a default. "Local-first with a cloud option" is not
what this is: a cloud option brings back accounts, keys, quotas, outage handling
and a privacy story that has to be argued rather than stated. The value here is
that none of that exists. The network is used only to check for and download
updates, and to fetch models a user explicitly asks for outside the installed
app.

## What finished looks like

A user installs one package and it works. They do not assemble a UI, fetch a
model, wire a runtime, or read a setup guide to get their first sentence typed.

It runs on the CPU of the machine they already have. No GPU is needed or used.
Dictation feels instant: the time from releasing the shortcut to the text
appearing is the number that matters most, measured on everyday laptops and
desktops, not on a workstation. The text is accurate enough that fixing it is
rare.

## Order of work

1. **Dictation.** Make it fast, accurate and dependable on Linux and Windows 11
   desktops, and pleasant to install, update and remove. This is the work.

Meetings and speaker-labelled transcripts are not on the roadmap. They were
dropped on 2026-10-03 to keep Dictate small: the Meeting mode, its speaker
labelling, its models and the libraries behind it (torch, pyannote) are being
removed, along with the plan for a separate beta app to carry them. One app,
one job.

## What we will not merge (for now)

- Anything that sends audio, transcripts or usage data off the device: hosted or
  "optional cloud" transcription, sync, telemetry, analytics, crash upload.
- Accounts, sign-in, subscriptions, licence keys or provider API keys.
- GPU-specific paths (CUDA, ROCm, DirectML). Dropped for their install and
  support cost; a later decision may bring them back.
- A second general speech engine alongside Parakeet. A new engine replaces the
  current one when it is better on CPU; it is not added as an option.
- Notes-app features: folders, tags, rich editing, AI summaries or rewrites.
  History exists so text can be recovered and exported, not managed.
- Meeting features: meeting recording modes, speaker labelling (diarization),
  call bots, calendar or conferencing integrations, and the libraries behind
  them.
- Features kept in the app but switched off, or a second build to carry them.
  A feature is in Dictate, or it is not.
- Features justified by selling. Dictate is not a commercial product; a feature
  earns its place by making local voice-to-text better.

This list is a guardrail, not a law. A change that conflicts with it needs this
file changed first, by pull request.

## Contribution rules

- One pull request, one topic. Do not bundle unrelated fixes or features; a
  few small related fixes can share one.
- Keep a pull request reviewable. One over about 5,000 changed lines is
  reviewed only in exceptional circumstances; split it.
- Open pull requests against `master`. One built on another unmerged branch is
  not reviewed until that branch lands, so wait for it, or say in the
  description what it depends on.
- Do not open a batch of small pull requests at once. Each one costs a review.
- Show it working. The description says what was run, on which commit, what it
  showed, and what was not run.

## Settings compatibility

Dictate reads the current settings only. It does not keep old, renamed or
removed settings working through permanent aliases. When a change makes an
existing setting invalid, such as a removed speech backend, the same change
moves it to the current equivalent on upgrade and keeps what the user chose
wherever it still exists. A user's notes and history are never dropped to
make a setting fit.

## How this file is used

`VISION.md` decides product scope for people and agents alike. Issues and pull
requests are reviewed against it. When this file changes, open work that no
longer fits it is stale and should be closed with a pointer to the line it
conflicts with, rather than finished.

This file is repository truth. Product direction is decided here and in GitHub
issues; earlier revisions were snapshots of an external Confluence page, which
is no longer authoritative.
