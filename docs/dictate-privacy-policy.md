# Dictate Privacy Policy Source Copy

Date: 2026-09-30

This is the repository source copy for the public Dictate privacy page at
`https://arcforge.au/privacy/dictate`. Publish the current contents there when
the page is next updated.

## Everything stays on the device

Dictate transcribes speech on the user's own machine. There is no account, no
subscription, no provider API key, and no hosted transcription. Microphone audio
never leaves the device, and Arc Forge does not receive dictation text, audio,
or transcripts at all.

Microphone audio is used only while you dictate and is not kept. Dictation history, notes, custom words, spelling substitutions and app
preferences are stored in the operating-system user data directory:

- Linux: `~/.config/dictate/` and `~/.local/share/dictate/`
- Windows: `%APPDATA%\dictate\` and `%LOCALAPPDATA%\dictate\`

`dictate export-local` exports history and notes to JSON. The Linux and Windows
uninstall scripts remove that data when run with `--remove-user-data` /
`-RemoveUserData`; removing the Linux `.deb` package leaves it in place, and it
can be deleted by hand.

## What does reach the network

Transcription itself never touches the network. Only these do, and none of
them carry dictation content:

- **Update checks.** Installs outside the Microsoft Store ask GitHub's release
  and tag endpoints whether a newer version exists when Dictate starts; the beta
  channel also asks the npm registry. Applying an update downloads the release
  from GitHub, or for source installs the update script from jsDelivr. These
  requests carry the usual information any web request does, such as an IP
  address, and no dictation content.
- **Model downloads, only outside the installed app.** The desktop app ships
  with the model it uses (Parakeet), so it downloads nothing to transcribe.
  Source installs, and models chosen from the command line that are not
  bundled, download model files from Hugging Face once, without a token.
- **Microsoft Store.** Installs from the Store are updated by the Store and
  subject to Microsoft's own install and update telemetry. Arc Forge does not
  receive dictation content through it.

Dictate has no analytics, no crash reporting, and no usage telemetry, and turns
off the telemetry its bundled libraries would otherwise send, before any of them
load: ONNX Runtime's Microsoft telemetry (the engine that runs Parakeet; it keeps
a device ID and uploads usage events to Microsoft by default) and Hugging Face
Hub telemetry.

Dictate 2026.9.27 and earlier did not turn these off. Those versions sent ONNX
Runtime usage events (session creation, graph optimisation and run timings,
with a device ID) to Microsoft whenever they transcribed, and Meeting mode (since
removed, #140) reported pipeline use to pyannote. Neither included audio or
transcript text.

## Diagnostics

Dictate writes local log files for troubleshooting. Logs contain app status,
file paths, model names, environment details and error text. They do not contain
dictated text: a finished dictation or note is logged as its length only. Logs
are never transmitted. Users should still check them for private names or a
Hugging Face token before attaching them to a bug report.

## Third-party software

Dictate bundles open-source libraries and models under their own licences,
including the Parakeet model (CC-BY-4.0). Notices ship with the
app as `THIRD_PARTY_NOTICES.md` and are published at
`https://arcforge.au/legal/notices`.

## Changes

Earlier versions of Dictate offered accounts, subscriptions, encrypted cloud
sync and hosted transcription. Those were removed on 2026-09-19 and the
supporting code was deleted. Any data previously held server-side is out of
scope for this document; the current application has no server side.
