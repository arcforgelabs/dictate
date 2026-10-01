# Dictate — Vision

Dictate turns speech into text on your own machine. Nothing you say leaves it.

Its first job is dictation: press a shortcut, speak, and the text is typed into
whatever app you are already using. Its second job, later, is longer
recordings and meetings: a local, speaker-labelled transcript you can keep and
export. Both are the same idea, voice to text locally, and nothing else.

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

Meetings, when they come, meet the same bar: one install, local, CPU, and no
setup beyond pressing record.

## Order of work

1. **Dictation.** Make it fast, accurate and dependable on Linux and Windows 11
   desktops, and pleasant to install, update and remove. This is the current
   work.
2. **Meetings and long recordings.** Local, speaker-labelled transcripts. This
   is in the vision but comes after dictation, is low priority, and never
   blocks a dictation release. Meeting features stay off the stable channel
   until dictation is where it should be.

Work that makes dictation slower, heavier or harder to install for the sake of
meetings is the wrong trade.

## What we will not merge (for now)

- Anything that sends audio, transcripts or usage data off the device: hosted or
  "optional cloud" transcription, sync, telemetry, analytics, crash upload.
- Accounts, sign-in, subscriptions, licence keys or provider API keys.
- GPU-specific paths (CUDA, ROCm, DirectML). Dropped for their install and
  support cost; a later decision may bring them back.
- A second general speech engine alongside Parakeet. A new engine replaces the
  current one when it is better on CPU; it is not added as an option.
- Notes-app features: folders, tags, rich editing, AI summaries or rewrites.
  History and meeting transcripts exist so text can be recovered and exported,
  not managed.
- Meeting features that need anything beyond the local machine: bots that join
  calls, calendar or conferencing integrations, cloud diarization.
- Features justified by selling. Dictate is not a commercial product; a feature
  earns its place by making local voice-to-text better.

This list is a guardrail, not a law. A change that conflicts with it needs this
file changed first, by pull request.

## How this file is used

`VISION.md` decides product scope for people and agents alike. Issues and pull
requests are reviewed against it. When this file changes, open work that no
longer fits it is stale and should be closed with a pointer to the line it
conflicts with, rather than finished.

This file is repository truth. Product direction is decided here and in GitHub
issues; earlier revisions were snapshots of an external Confluence page, which
is no longer authoritative.
