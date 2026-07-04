# Dictate Pro subscription architecture

This document defines the first paid Dictate subscription implementation.

Working product name: `Dictate Pro`.

Research and planning date: 2026-06-25.

## Product contract

Dictate Pro is the first and only paid subscription tier. There is no separate
Standard tier for the initial implementation.

Customer-facing promise:

- For people with `1-2` important team meetings per week.
- Turn important meetings into speaker-labelled transcripts.
- Includes `25` one-hour diarized meeting recordings per month.
- Uploaded meetings use hosted xAI REST/batch transcription.
- Everyday push-to-talk dictation remains local/on-device by default.

Initial price target:

- `$7 AUD/month`
- Cost rule: charge approximately API cost plus `30%`
- API budget: `$7 / 1.3 = $5.38 AUD/month`
- Planning exchange rate: `1 USD ~= 1.45 AUD`, so API budget is about
  `$3.71 USD/month`

The included `25` meeting hours/month leaves room for xAI STT, LLM
post-processing later, retries, exchange-rate movement, and unusually long
files. Internally, the system may warn at `20` hours and hard-stop or require an
add-on above `25` included meeting hours.

## Non-goals for the first subscription

- Do not ship multiple paid tiers initially.
- Do not include open-ended "unlimited" hosted transcription.
- Do not expose Arc Forge's xAI API key to the desktop app.
- Do not include `30 min/day` of live xAI streaming dictation in the `$7 AUD`
  plan. Live hosted dictation should be a later add-on or higher tier.
- Do not make summaries/action items block the first paid release if the current
  product direction is still transcript-first. The entitlement model should
  support summaries later.

## Required system shape

Dictate Pro needs a service-side control plane. The existing local BYO-key xAI
path is not enough for subscription billing because it stores or reads the
customer's own provider key on the device.

Required components:

- Billing provider: Stripe, Microsoft recurring billing, or another compliant
  provider selected before Store submission.
- Account identity service: maps a signed-in user/device to a subscription.
- Entitlement service: answers whether the user has active Dictate Pro access.
- Usage meter: records billable audio seconds and plan counters.
- Transcription relay: server-owned xAI integration that keeps the xAI API key
  off client devices.
- Job store: durable records for uploads, processing state, transcript segments,
  usage debits, and errors.
- Desktop client integration: sign-in, entitlement display, upload flow, and
  local fallback.

## Packaging and install requirements

The architecture must preserve Dictate's public install promise:

- Windows users should get a one-click Microsoft Store install, with signed
  direct-download installers as fallback.
- Linux users should get a packaged desktop install, currently focused on `.deb`
  through the existing Tauri/PyInstaller release flow.
- The default installer must not require users to install Python, Rust, CUDA,
  Visual Studio build tools, system ML libraries, or model toolchains manually.

This changes the implementation plan in one important way: hosted Dictate Pro is
the packaged-product path, while WhisperX remains an optional experimental local
path.

Default public installers should include:

- Tauri shell,
- frozen Dictate Python engine,
- existing local faster-whisper dictation path,
- sign-in, entitlement, upload, usage, and hosted meeting-processing UI,
- no bundled WhisperX, pyannote, PyTorch, CUDA stack, or Hugging Face-gated
  diarization models.

Default public installers should not include WhisperX until all of these are
proven:

- Windows packaging works without user-installed build tools,
- Linux `.deb` package size remains acceptable,
- CPU-only performance is tolerable for real one-hour meetings,
- GPU acceleration degrades gracefully when unavailable,
- pyannote/Hugging Face model terms and download flow are acceptable for public
  users,
- Store certification/privacy language covers local model downloads,
- support burden is acceptable.

If WhisperX is later exposed, ship it as one of these:

- an experimental optional download managed inside Dictate,
- a developer/advanced extra installed outside the public Store package,
- a separate "local meeting diarization" package after benchmarking,
- a server-side/self-hosted worker path, not the default desktop package.

The packaged app must fail soft:

- if hosted entitlement is missing, local dictation still works,
- if quota is exhausted, local dictation still works,
- if the hosted relay is unreachable, the meeting upload stays queued or fails
  with a retryable state,
- if optional WhisperX is unavailable, the UI hides or disables that path rather
  than breaking startup.

## Minimum system requirements

Minimum requirements for the default packaged app:

| Platform | Minimum |
| --- | --- |
| Windows | Windows 10 22H2 or Windows 11, x64, Microsoft Store or signed installer support |
| Linux | Modern x64 desktop Linux with glibc, audio input, tray/desktop integration; Ubuntu 22.04+ or Debian 12+ class systems for `.deb` |
| CPU | 4-core x64 CPU |
| RAM | 8 GB minimum |
| Disk | 2 GB free for app, logs, local config, and small/medium local STT model cache |
| Network | Required for Dictate Pro sign-in, subscription checks, hosted meeting upload, and updates |
| Audio | Working microphone or uploaded meeting audio file |

Recommended requirements for a reliable default experience:

| Platform | Recommended |
| --- | --- |
| Windows | Windows 11 x64 |
| Linux | Ubuntu 24.04 LTS x64 or equivalent |
| CPU | Recent 6-core x64 CPU |
| RAM | 16 GB |
| Disk | 5-10 GB free if using local transcription models heavily |
| Network | Stable broadband for meeting uploads |

Experimental local WhisperX requirements:

| Component | Practical requirement |
| --- | --- |
| CPU-only | Works only as a slow/offline path; not suitable as the default one-click meeting product until benchmarked |
| RAM | 16 GB minimum, 32 GB recommended for long meetings and larger models |
| GPU | NVIDIA GPU with 8 GB+ VRAM recommended for one-hour meeting turnaround |
| Disk | 10-20 GB free for WhisperX, PyTorch, alignment models, pyannote models, and caches |
| Dependencies | Optional `.[whisperx]` install plus accepted pyannote/Hugging Face model terms |

These requirements mean the commercial Dictate Pro implementation should rely
on hosted xAI batch processing for packaged reliability. Local WhisperX is a
benchmark and advanced/private-mode direction, not the minimum system baseline.

## Plan entitlement

`Dictate Pro` entitlement:

- `plan_id`: `dictate_pro_monthly`
- `included_batch_meeting_seconds`: `90_000` seconds (`25` hours)
- `included_streaming_seconds`: `0` seconds for initial release
- `provider`: `xai`
- `stt_mode`: `rest_batch`
- `diarization`: enabled
- `word_timestamps`: enabled when returned by provider
- `summary`: disabled initially or enabled behind the same entitlement once the
  transcript-first path is stable

Usage windows reset monthly at the billing-period boundary from the billing
provider, not at calendar-month midnight.

## Billing requirements

The billing integration must:

- create and manage `Dictate Pro` subscriptions,
- receive webhook events for checkout completion, renewal, payment failure,
  cancellation, refund, and chargeback,
- keep an internal subscription state table independent of webhook delivery
  order,
- expose current entitlement and billing-period dates to the app,
- never trust only client-reported subscription state,
- support a grace state for recent payment failures,
- record the commerce provider transaction/subscription ids for audit and
  support.

For Microsoft Store distribution, follow
[msstore-in-app-subscriptions.md](msstore-in-app-subscriptions.md). A non-game PC
app may use Microsoft in-product purchase APIs or a secure third-party purchase
API, but Partner Center metadata must disclose the subscription and price range.

## Identity requirements

The desktop app needs a stable account identity before hosted processing.

Minimum viable options:

- email magic link,
- OAuth sign-in,
- Microsoft account sign-in if Store-aligned,
- license key tied to email for a lower-friction first release.

The account system must issue short-lived access tokens for the desktop app.
Refresh tokens, if used, must be stored in the OS secret store. Tokens must be
revocable server-side.

Device identity should be separate from account identity:

- `account_id`: who pays and owns entitlement,
- `device_id`: installation/device used for abuse tracking and diagnostics,
- `session_id`: short-lived auth/session context.

## Usage-metering requirements

Meter usage by processed audio duration, not by file size.

Each transcription job must record:

- `job_id`
- `account_id`
- `device_id`
- `plan_id`
- `mode`: `batch_meeting` or future `streaming_dictation`
- `provider`: `xai`
- `provider_model`
- `requested_diarization`
- `audio_duration_seconds`
- `billable_seconds`
- `billing_period_start`
- `billing_period_end`
- `provider_request_id` if available
- `status`
- `created_at`, `started_at`, `completed_at`
- retry count and error classification

Debit usage only once per successful processing result. Failed jobs should be
tracked separately for margin analysis. If a failed provider request still
incurs provider cost, count it in internal COGS but do not necessarily count it
against the user's included hours.

Usage thresholds:

- warn at `20` hours used,
- warn again at `24` hours used,
- stop hosted meeting processing or require an add-on after `25` included hours,
- allow local/on-device dictation regardless of hosted quota state.

## Transcription relay requirements

The relay owns the xAI API key and calls `POST https://api.x.ai/v1/stt`.

Request behavior:

- Accept an uploaded audio file or app-generated recording.
- Validate account entitlement before accepting large uploads.
- Validate remaining quota before provider submission.
- Normalize or reject unsupported formats.
- Compress long recordings before upload when needed.
- Send xAI fields: `diarize=true`, `format=true`, and a language hint when known.
- Preserve provider duration in the job record.
- Convert provider output into Dictate transcript segments.
- Delete raw audio after successful transcript persistence unless the user has
  explicitly opted into retention.

The relay must not:

- return xAI credentials to the client,
- trust client-supplied duration for billing,
- keep raw audio by default,
- block a desktop UI thread while processing.

## Long-meeting processing

xAI's public STT docs list a `500 MB` maximum file size. Most one-hour
compressed meeting recordings should fit under that. The implementation should
still support chunking for long/high-bitrate files.

Chunking requirements:

- split files only at stable audio boundaries where possible,
- keep `chunk_sequence`, `chunk_start_seconds`, and `chunk_end_seconds`,
- preserve transcript ordering across chunks,
- normalize speaker labels across chunks as well as practical,
- avoid double-charging retries for the same successful chunk,
- surface partial processing state in the UI.

For the first release, it is acceptable to support one-hour recordings directly
and defer sophisticated multi-hour chunk reconciliation if the upload path
rejects or queues files above a conservative duration/size limit.

## Local WhisperX experiment

The repo now has the start of a local WhisperX backend:

- optional dependency group: `.[whisperx]`,
- backend id: `whisperx`,
- default model: `large-v3`,
- local UI catalog entry: `whisperx/large-v3`,
- adapter: `src/dictate/stt/whisperx_backend.py`,
- diarization path: WhisperX transcription, alignment, pyannote diarization,
  then speaker-labelled text formatting.

This is not the Dictate Pro hosted relay. Treat it as the local/open-source
benchmark path for deciding whether some meeting processing can run without API
cost. It requires the user or test machine to install WhisperX and provide a
Hugging Face token for pyannote model access with `DICTATE_HF_TOKEN`,
`HUGGINGFACE_HUB_TOKEN`, or `HF_TOKEN`.

Open implementation work:

- benchmark one-hour meetings on common laptops,
- decide whether WhisperX should be hidden behind an experimental flag,
- add transcript-segment persistence rather than only formatted text,
- add speaker-label reconciliation across chunks,
- verify Windows packaging impact before exposing it in Store builds.

### WhisperX commercial boundaries

The local WhisperX path has different commercial boundaries from hosted Dictate
Pro.

Code/package layer:

- WhisperX is BSD-2-Clause licensed. Commercial use and redistribution are
  generally allowed when copyright/license notices are preserved.
- faster-whisper is MIT licensed. Commercial use and redistribution are
  generally allowed when notices are preserved.
- pyannote.audio code is MIT licensed. Commercial use and redistribution are
  generally allowed when notices are preserved.

Model/data layer:

- The current pyannote `speaker-diarization-community-1` model card lists the
  model license as `cc-by-4.0`.
- CC-BY-4.0 allows commercial use, but requires attribution and preservation of
  license notices.
- The model is gated on Hugging Face. Users must accept the model conditions and
  provide a Hugging Face token before downloading or using it.
- The model card says users agree to share contact information and may receive
  occasional pyannote communications after accepting access conditions.
- pyannote documents offline use after cloning/downloading the model, but the
  initial access still depends on accepted conditions and an access token.

Commercial product implication:

- Dictate can offer WhisperX as an optional local/experimental feature, but the
  app must not silently bundle or auto-download gated pyannote model files
  without making the user/license step explicit.
- If Arc Forge bundles pyannote model weights in an installer, Arc Forge must
  satisfy CC-BY attribution and any accepted distribution conditions. This should
  get legal review before public Store release.
- Safer first release: do not bundle WhisperX/pyannote models in default
  installers. Require the user to opt in, accept upstream model terms, and supply
  their own Hugging Face token.
- The privacy policy and UI must disclose any telemetry/configuration behavior
  from pyannote/Hugging Face model access if this path is exposed.
- Do not market local WhisperX diarization as part of paid Dictate Pro until the
  license, attribution, packaging, telemetry, support, and benchmark obligations
  are cleared.

### Option B: Arc Forge bundles WhisperX/pyannote assets

Option B means Arc Forge ships the local diarization stack and model assets as
part of an Arc Forge-managed installer, optional component, or first-run
download. This gives users a cleaner product experience, but Arc Forge becomes
responsible for upstream license compliance, model redistribution checks,
packaging size, update mechanics, and support.

Do not ship Option B until every gate below is complete.

Legal and licensing gates:

- Confirm the exact model identities and versions to ship:
  - WhisperX package version,
  - faster-whisper/CTranslate2 versions,
  - pyannote.audio version,
  - pyannote diarization model repo and revision,
  - alignment model repos and revisions used by WhisperX.
- Record the license for each code package and model artifact.
- Confirm whether the selected pyannote model's gated Hugging Face conditions
  allow Arc Forge to redistribute model weights inside a commercial app or
  Arc Forge-hosted model download.
- If redistribution is not explicitly clear, get written permission or do not
  bundle the weights.
- Preserve all upstream copyright notices and license files.
- Add CC-BY-4.0 attribution for `pyannote/speaker-diarization-community-1` if
  that model is shipped.
- State whether Arc Forge modified any model files. If unmodified, say so.
- Add a third-party notices file to the app package and repository.
- Add an in-app Legal/About surface that links to third-party notices.
- Have counsel or an explicit internal legal approver review the exact notices,
  redistribution basis, and Store-facing wording before release.

Suggested attribution wording, pending legal review:

```text
This product includes or can download pyannote speaker diarization models.
pyannote/speaker-diarization-community-1 is provided by pyannote and licensed
under Creative Commons Attribution 4.0 International (CC BY 4.0):
https://creativecommons.org/licenses/by/4.0/

Model source: https://huggingface.co/pyannote/speaker-diarization-community-1
No model weight modifications by Arc Forge Labs unless otherwise stated.
```

Packaging gates:

- Decide whether model assets are bundled in the installer or downloaded after
  install.
- Prefer optional first-run download over bundling in the default installer
  unless package size and Store certification are proven.
- Keep default Dictate install functional without the optional local diarization
  component.
- Verify Windows MSIX/Microsoft Store package size, install time, and startup
  time with the optional assets present.
- Verify Windows direct MSI/NSIS fallback package size and signing behavior.
- Verify Linux `.deb` package size and install/remove behavior.
- Verify uninstall removes only Dictate-managed model files and does not delete
  unrelated Hugging Face caches.
- Add checksums for Arc Forge-hosted model downloads.
- Version model artifacts independently from the app so model updates do not
  require a full app release when avoidable.
- Support resumable downloads for large model assets.

Runtime gates:

- Detect whether local diarization assets are installed.
- Hide or disable the local diarization option until assets are present.
- Provide a clear installer/download progress state.
- Fail soft when local diarization cannot load: hosted meeting upload and local
  plain dictation must still work.
- Use local diarization only when the user explicitly selects local/private
  meeting processing.
- Add a model-health check to `doctor`.
- Add a way to remove local diarization assets from settings.

Privacy and telemetry gates:

- Update Arc Forge privacy policy before release.
- Disclose that local diarization model files are stored on the device.
- Disclose whether any model download request goes to Arc Forge, Hugging Face,
  pyannote, or another CDN.
- Disclose any telemetry emitted by pyannote or Hugging Face tooling, or disable
  it where possible.
- Do not upload audio for local WhisperX processing unless the user separately
  chooses a hosted feature.
- Keep logs free of transcript text, audio paths containing private names, HF
  tokens, and model download credentials.

UI/consent gates:

- Add a first-use screen for local diarization before downloading assets.
- Make the feature name explicit: "Experimental local diarization".
- Show hardware and disk requirements before install.
- Show links to:
  - Arc Forge terms,
  - Arc Forge privacy policy,
  - third-party notices,
  - pyannote model source,
  - CC-BY-4.0 license.
- Require the user to confirm the optional component download.
- Do not imply pyannote, Hugging Face, WhisperX, or OpenAI endorse Dictate.

Microsoft Store gates:

- Update Store metadata if the package includes or downloads substantial local
  AI model assets.
- Update privacy/certification notes to explain local model download and local
  processing.
- Confirm Store package validation accepts package size and installed file
  layout.
- Confirm age-rating and AI disclosures still match the actual app behavior.
- Re-run Windows install/runtime smoke on a clean VM with no developer tools,
  no Python, no Rust, and no pre-existing model cache.

Support gates:

- Document expected disk usage.
- Document expected CPU/GPU behavior.
- Document that CPU-only local meeting diarization may be slow.
- Add support diagnostics for missing/corrupt model assets.
- Add a support procedure for clearing and re-downloading local diarization
  assets.
- Add benchmark results for at least:
  - one common Windows laptop,
  - one common Windows desktop,
  - one Ubuntu laptop/desktop,
  - CPU-only,
  - NVIDIA GPU where available.

Release decision:

- Ship Option B only if it keeps the public install experience reliable.
- If package size, model terms, hardware variability, or support burden are not
  acceptable, keep WhisperX as Option A: user-supplied token and explicit
  experimental setup.

## Public notice and deployment pathway requirements

The public legal surface now needs to be part of the release checklist, not a
separate website afterthought.

Required public notices before enabling WhisperX/pyannote in a public build:

- Arc Forge legal hub links to `/third-party-notices`.
- Dictate privacy policy discloses optional local diarization model downloads,
  Hugging Face/token access, local model cache storage, and the fact that local
  diarization does not upload audio to Arc Forge unless the user separately
  chooses a hosted workflow.
- Third-party notices name the major local speech/diarization dependencies:
  WhisperX, faster-whisper, pyannote.audio, and the pyannote
  `speaker-diarization-community-1` model.
- The pyannote Community-1 notice includes CC-BY-4.0 attribution and a link to
  the model card.
- The notice states that third-party projects do not endorse Dictate unless
  separately stated.
- The website sitemap includes the notice page so it is discoverable.

Arc Forge website deployment path:

- Pull latest `origin/master` in `~/repos/arc-forge-website`.
- Edit source pages under `src/pages` and shared navigation under
  `src/partials`.
- Run the website build/test/deploy path through `bash deploy.sh`, which builds
  `dist/`, runs site tests, and rsyncs the built site to
  `prod-forge-gateway:/srv/arcforge.au/`.
- After deployment, verify that `/legal`, `/privacy/dictate`, and
  `/third-party-notices` are reachable on `https://arcforge.au`.

Required packaged-app notice artifacts:

- Include a local `THIRD-PARTY-NOTICES` or equivalent generated notice file in
  Windows and Linux packages.
- Add an in-app Legal/About view linking to:
  - Arc Forge Terms,
  - Arc Forge Privacy Policy,
  - Dictate Privacy Policy,
  - Third-Party Notices,
  - pyannote model card,
  - CC-BY-4.0 license.
- Add a Settings path to remove optional downloaded local diarization assets.
- Ensure support bundles and logs redact HF tokens, provider API keys, access
  tokens, file paths where practical, and transcript text.

Store and listing requirements:

- Microsoft Store metadata must disclose any paid Dictate Pro subscription,
  included usage, renewal period, and price range.
- Store privacy notes must match actual behavior: local dictation, optional
  hosted processing, optional model downloads, local cache, and third-party
  provider requests.
- If the Store build downloads large model assets after install, the listing
  and first-use UI must set that expectation before download.
- If WhisperX remains experimental, the Store-facing build should hide or gate
  it until the legal, packaging, and support gates are complete.

## UI requirements for notices and optional local diarization

Additions to the build scope:

- Settings > Legal/About:
  - current app version,
  - license/legal links,
  - third-party notices link,
  - privacy links,
  - copy diagnostics summary button that redacts secrets.
- Settings > Models:
  - installed local STT models,
  - installed local diarization assets,
  - disk usage,
  - install/update/remove actions,
  - health status and last error.
- First-use local diarization consent:
  - title: `Experimental local diarization`,
  - plain-language summary of hardware/disk requirements,
  - links to third-party notices, pyannote model card, and CC-BY-4.0,
  - statement that Hugging Face model access may require account/token and
    acceptance of model access conditions,
  - explicit confirmation before downloading model assets,
  - no endorsement wording for WhisperX, Hugging Face, pyannote, or OpenAI.
- Hosted meeting upload disclosure:
  - clear Hosted/Local mode distinction,
  - provider shown before upload,
  - included monthly hours and remaining quota,
  - privacy link before first hosted upload.
- Failure states:
  - missing HF token,
  - gated model access not accepted,
  - insufficient disk,
  - CPU-only slow path warning,
  - corrupt/missing model cache with repair action,
  - hosted quota reached while local dictation remains available.

## Desktop app requirements

The desktop app must add:

- Dictate Pro sign-in/sign-out.
- Current entitlement and usage display.
- Meeting upload or meeting-recording flow that is clearly hosted.
- Quota warnings at `20` and `24` included hours.
- Clear "quota reached" state with local dictation still available.
- Privacy disclosure before hosted upload.
- A settings surface showing billing status and renewal date.

Provider behavior:

- Local/on-device remains the default for ordinary push-to-talk dictation.
- Dictate Pro meeting mode uses hosted xAI through the relay.
- Existing BYO-key xAI support can remain for developer/advanced use, but must
  be visually distinct from Dictate Pro.

## Backend API sketch

Current hosted Arc Forge gateway endpoints used by the desktop client:

- `POST /api/account/auth/login-code`
- `POST /api/account/auth/verify-code`
- `POST /api/account/auth/token`
- `GET /api/account/commerce`
- `GET /api/dictate/entitlement`
- `GET /api/dictate/usage`
- `POST /api/dictate/jobs`
- `POST /api/dictate/jobs/{job_id}/audio-upload-url`
- `PUT {signed_object_upload_url}`
- `POST /api/dictate/jobs/{job_id}/audio-upload-complete`
- `POST /api/dictate/jobs/{job_id}/audio` as a compatibility fallback when the
  gateway has not enabled signed object uploads
- `GET /api/dictate/jobs/{job_id}`
- `GET /api/dictate/jobs/{job_id}/transcript`

The desktop default base URL is `https://console.arcforge.au`. The shared Arc
Forge Gateway owns account, commerce, entitlement, and server-side provider
credential custody. The Dictate desktop app must not call LiteLLM directly or
hold Arc Forge provider keys.

Legacy local Pro control-plane endpoints remain for localhost development and
local workflows:

- `POST /v1/auth/start`
- `POST /v1/auth/complete`
- `GET /v1/me`
- `GET /v1/entitlements`
- `GET /v1/usage/current`
- `POST /v1/meetings`
- `POST /v1/meetings/{meeting_id}/audio`
- `GET /v1/meetings/{meeting_id}`
- `GET /v1/meetings/{meeting_id}/transcript`
- `POST /v1/billing/checkout`
- `POST /v1/billing/portal`

Billing webhooks should be provider-specific and not exposed to the desktop app.

## Data model sketch

Core tables or collections:

- `accounts`
- `devices`
- `subscriptions`
- `entitlements`
- `usage_periods`
- `usage_events`
- `meeting_jobs`
- `meeting_chunks`
- `transcript_segments`
- `billing_events`
- `provider_events`

Transcript segment fields should align with the transcript-first plan in
[TRANSCRIPTION_PLAN.md](TRANSCRIPTION_PLAN.md): note/meeting id,
provider/model, speaker id/label, text, start/end timestamps, sequence, status,
and errors.

## Security and privacy requirements

- Store provider secrets only server-side.
- Store desktop auth refresh tokens only in the OS secret store.
- Use TLS for all app-service traffic.
- Use short-lived upload URLs or authenticated streaming uploads.
- Encrypt raw audio at rest if any temporary object storage is used.
- Delete temporary audio after transcript persistence.
- Keep support logs free of audio, transcript text, access tokens, provider
  keys, and payment details.
- Provide account deletion and local sign-out paths.
- Update the privacy policy before shipping hosted subscription processing.

## Observability and COGS requirements

Track enough telemetry to answer:

- average included hours used per active subscriber,
- p50/p90/p99 meeting length,
- provider cost per subscriber,
- retry and failure cost,
- quota-hit rate,
- conversion by qualification answer,
- churn by usage pattern,
- gross margin by billing period.

Do not log transcript contents for analytics.

## Production integration — website, Stripe, and this app (P0)

Public Dictate Pro marketing is deployed on the Arc Forge website
(`/download/dictate`), but **Upgrade to Pro** is still a placeholder (`/login`).
This was captured as production P0 in:

- **This repo:** [archive/goals-2026-07-05.md](archive/goals-2026-07-05.md) -> *Wire Dictate Pro purchase + entitlements*
- **Website repo:** `arc-forge-website/STATUS.md` → *Production — must handle*

Until the following are connected, do not treat Dictate Pro as a purchasable
product:

| Layer | Responsibility |
|---|---|
| Stripe | Dictate Pro product/price; Checkout Session; subscription webhooks |
| Gateway / commerce API | Arc Forge Checkout/portal links, Stripe webhook → shared commerce subscription and entitlement |
| Account service | Persist portal account/session state; answer `GET /api/dictate/entitlement` for active Pro |
| Website | Real checkout URL on **Upgrade to Pro**; post-purchase onboarding links |
| Desktop app (dictate) | Sign-in, read entitlement from service, gate hosted meeting mode |
| Portal | Show plan, renewal, usage; link to Stripe Customer Portal where needed |

Minimum E2E acceptance: website CTA → pay → account entitled → app unlocks Pro
features (meeting transcripts, early access) without manual intervention.

## Rollout gates

Before public rollout:

- Confirm xAI diarization has no separate surcharge in the xAI console/account
  terms.
- Confirm STT billing granularity and rounding.
- Confirm upload size and rate limits.
- Choose billing provider and update Store metadata.
- Update privacy policy and terms.
- Implement entitlement checks before provider calls.
- Implement server-side usage metering.
- Run end-to-end tests for active, expired, grace, quota-warning, and
  quota-exceeded accounts.
- Add support procedures for failed jobs and refund/credit decisions.
