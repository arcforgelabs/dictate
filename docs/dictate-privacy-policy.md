# Dictate Privacy Policy Source Copy

Date: 2026-07-06

This is the repository source copy for the public Dictate privacy page at
`https://arcforge.au/privacy/dictate`. Publish the current contents there before
stable promotion when Dictate Pro sync or hosted Pro models are enabled.

## Local-First Dictation

Dictate can run without a Dictate Pro account. In local mode, microphone audio,
dictation history, long-form notes, transcript segments, hotwords, spelling
substitutions, model choices, and app preferences are stored on the user's
device. Arc Forge does not receive local dictation text merely because the app
is installed, opened, or used.

Dictate stores local data in the operating-system user data directory and uses
the operating-system secret store where available for credentials and account
tokens. Users can export local data from the app and can remove local data by
uninstalling the app and deleting the local Dictate data directory.

## Dictate Pro Sign-In

Signing in to Dictate Pro identifies the account, registers the current device,
checks subscription and entitlement status, and enables access to Pro features.
Signing in does not automatically upload existing local dictations. Encrypted
cloud sync starts only after the user explicitly chooses to sync dictations
across devices.

Arc Forge may process account email address, device label, device id, session
state, subscription status, entitlement checks, update metadata, and usage
counters needed to operate Dictate Pro.

## Encrypted Cloud Sync

If the user enables Dictate Pro cloud sync, Dictate encrypts synced dictation
content on the device before upload. Synced content includes dictation history,
long-form note metadata, transcript segments, meeting transcript speaker and
timestamp metadata, archive state, synced hotwords, spelling substitutions,
custom vocabulary, and portable app preferences.

Arc Forge stores encrypted sync records and server-visible metadata required to
sync devices, such as account id, device id, collection name, record id,
revision, update time, payload size, cursor state, and deletion state. Arc Forge
staff and server operators cannot read synced dictation text, transcript
segments, synced lexicon terms, or meeting transcript content from those cloud
records without the user's account data key.

Dictate does not sync raw audio by default. Dictate does not sync API keys,
provider credentials, refresh tokens, local model cache paths, microphone
choices, output-device choices, CPU/GPU/runtime choices, or OS-specific hotkeys.

## Recovery And Devices

When encrypted sync is enabled, Dictate may show a recovery key. The recovery
key is controlled by the user and can restore synced dictations on a new device
if trusted devices are unavailable. Arc Forge cannot recover encrypted synced
content if all trusted devices and the recovery key are lost.

Users can view registered devices, approve new devices, and revoke devices.
Revoked devices are blocked from future sync. Local data already stored on a
revoked device is not remotely erased by device revocation.

## Hosted Pro Transcription

Hosted Pro transcription is separate from encrypted sync. A hosted transcription
job intentionally sends audio to Arc Forge and, where applicable, to a hosted
model provider for processing. Hosted jobs are metered for entitlement and usage
limits. The Dictate control plane stores hosted results as server-managed
encrypted artifacts (account/device/job AAD binding); readable transcript text
is not retained server-side after bounded delivery and acknowledgement.

Provider-side processing, retention, and deletion behavior are governed by the
provider terms disclosed for the hosted model path. Users who do not want audio
to leave the device should use local transcription.

## Logs, Support, Analytics, And Crash Reports

Routine logs, analytics, crash reports, billing records, and support tooling
must not contain plaintext dictated content, transcript segments, synced
lexicon terms, raw audio, API keys, provider credentials, refresh tokens, or
payment details.

If a user sends screenshots, logs, or exported data to Arc Forge for support,
Arc Forge processes the submitted material for support purposes. Users should
remove private information before sharing support materials.

## Export And Deletion

Users can export local Dictate data from the app. Dictate Pro users can request
export of account-owned cloud sync records and can delete cloud sync records for
their account. Deleting cloud data removes cloud sync records, device sync
state, key envelopes, and cursors for the account. It does not delete local
dictations already stored on the user's devices.

## Stable Promotion Checklist

Before a stable release that includes Dictate Pro sync or hosted Pro models:

1. Publish this policy copy, or a stricter replacement, to the public privacy
   URL.
2. Confirm the public terms explain Dictate Pro subscriptions, hosted model
   usage, encrypted sync, account deletion, and support boundaries.
3. Confirm Store metadata and in-app onboarding match the current product.
4. Run `python scripts/cloud_sync_privacy_audit.py` on the release commit.
