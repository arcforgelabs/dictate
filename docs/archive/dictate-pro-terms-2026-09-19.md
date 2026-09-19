# Dictate Pro Terms Source Copy

Date: 2026-07-06

This is repository source copy for Dictate Pro product terms. Publish the
current commercial/legal version at `https://arcforge.au/terms` or the relevant
product terms page before stable promotion.

## Dictate Base App

Dictate is a local-first desktop dictation app. The base app can be used without
a Dictate Pro account. Local transcription, local history, local notes, local
settings, and local model files remain on the user's device unless the user
chooses a feature that sends data away from the device.

## Dictate Pro Account

Dictate Pro adds account-backed features such as subscription entitlement,
hosted model access, usage metering, device registration, encrypted cloud sync,
cloud export, and cloud deletion.

The user is responsible for keeping account credentials, trusted devices, and
recovery keys safe. If every trusted device and recovery key is lost, encrypted
synced dictation content may be unrecoverable.

## Encrypted Cloud Sync

Encrypted cloud sync is optional. The user must explicitly enable it after
signing in. Dictate encrypts synced dictation content before upload. Arc Forge
stores encrypted records and sync metadata to operate multi-device sync.

Cloud sync is intended to synchronize user-owned Dictate data across that
user's devices. Users must not use cloud sync to upload unlawful content or
content they do not have the right to store.

Device revocation prevents future sync from that device. It does not guarantee
remote erasure of data already present on that device.

## Hosted Pro Models

Hosted Pro transcription is separate from cloud sync. When the user starts a
hosted transcription job, audio may be sent to Arc Forge and to selected hosted
model providers. Hosted model usage is governed by Dictate Pro entitlement and
usage limits. Arc Forge may throttle, reject, or stop hosted jobs that exceed
plan limits, technical limits, abuse limits, or provider availability.

Users should review important transcription output before relying on it. Speech
recognition can be incomplete or inaccurate, especially with noise, overlapping
speech, accents, specialist vocabulary, or poor recording conditions.

## Billing And Subscriptions

Paid Dictate Pro plans may be sold through Microsoft Store in-product purchase,
Stripe, Paddle, or another disclosed purchase provider. The checkout flow must
identify the transaction provider and show the subscription terms, renewal
period, price, taxes where applicable, and cancellation path before purchase.

If an active subscription is discontinued, the user should retain access to the
paid digital service until the paid period expires, subject to abuse,
availability, and legal restrictions.

## Export And Deletion

Users can export local Dictate data from the app. Dictate Pro users can request
export or deletion of account-owned cloud records. Cloud deletion removes cloud
sync records, device sync state, key envelopes, and cursors for the account; it
does not delete local data already stored on devices.

## Support Boundary

Users should not send private dictated content, raw audio, API keys, provider
credentials, refresh tokens, payment details, or confidential third-party data
in support requests unless they intentionally choose to share it for support.
Arc Forge uses support materials to investigate and resolve the support issue.

## Stable Promotion Checklist

Before stable promotion:

1. Confirm public terms include the same or stricter protections as this file.
2. Confirm Store metadata discloses paid features and hosted generative AI where
   enabled.
3. Confirm in-app onboarding separates sign-in, encrypted sync consent, and
   hosted model use.
