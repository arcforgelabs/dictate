# Dictate

Local-only desktop dictation. Read `VISION.md` before changing product
behaviour.

## Direction

Transcription runs on the user's machine. No accounts, no subscriptions, no API
keys, no hosted models, no network call in the transcription path.

Account, subscription, cloud sync and hosted-transcription code was removed on
2026-09-19. Do not reintroduce a cloud path: no accounts, no API keys, no
hosted models, no sync. What was removed and why is in
`docs/local-only-audit.md`.

## Where things are recorded

GitHub is the record. Product direction lives in `VISION.md`, work in GitHub
issues, and code, configuration, tests and implementation contracts are
repository truth.

Atlassian is legacy. Confluence no longer owns the vision and Jira no longer
owns the work. Any remaining pointer to a Confluence space, a Jira project
(`OPS`, `DEL`), or the Assets registry is stale — strip it when you touch the
file rather than following it.
