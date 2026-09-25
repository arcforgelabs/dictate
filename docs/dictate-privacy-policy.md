# Dictate Privacy Policy Source Copy

Date: 2026-09-26

This is the repository source copy for the public Dictate privacy page at
`https://arcforge.au/privacy/dictate`. Publish the current contents there when
the page is next updated.

## Everything stays on the device

Dictate transcribes speech on the user's own machine. There is no account, no
subscription, no API key, and no hosted transcription. Microphone audio never
leaves the device, and Arc Forge does not receive dictation text, audio, or
transcripts at all.

Microphone audio is used only while you dictate and is not kept. Dictation
history, notes, custom words, spelling substitutions and app preferences are
stored in the operating-system user data directory:

- Linux: `~/.config/dictate/` and `~/.local/share/dictate/`
- Windows: `%APPDATA%\dictate\` and `%LOCALAPPDATA%\dictate\`

Users can export local data from the app, and can remove it by uninstalling
Dictate and deleting that directory.

## What does reach the network

Transcription itself never touches the network. Only these do, and none of
them carry dictation content:

- **Model downloads, only outside the installed app.** The installed app ships
  with its speech model (Parakeet), so it downloads nothing to transcribe.
  Source installs, and other local models chosen from the command line,
  download model files from the model host (Hugging Face) once. That sends the
  usual information any file download does, such as an IP address, and no audio
  or transcript.
- **Update checks.** Dictate asks GitHub whether a newer release exists, and
  downloads it when the user chooses to update. This carries the current
  version and update channel, and no dictation content.
- **Microsoft Store.** Installs from the Store are subject to Microsoft's own
  handling of install and update telemetry. Arc Forge does not receive
  dictation content through it.

Dictate has no analytics, no crash reporting, and no usage telemetry.

## Diagnostics

Dictate writes local log files for troubleshooting. Logs can contain file
paths, model names and error text. They are never transmitted. Dictation text
can be sensitive, so users should check logs before attaching them to a bug
report.

## Changes

Earlier versions of Dictate offered accounts, subscriptions, encrypted cloud
sync and hosted transcription. Those were removed on 2026-09-19 and the
supporting code was deleted. Any data previously held server-side is out of
scope for this document; the current application has no server side.
