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

<!-- arc-forge-org-consistency:start -->
## Pull requests

Use `.github/pull_request_template.md`. Keep these sections current in the pull request body:

- What Problem This Solves
- User Impact
- Why This Change Was Made
- Evidence

Evidence names the command, the commit, the result, and what was not run. A screenshot is the real product, with the viewport and whether the data was synthetic or live. If the proof could not be run, name the gap in Evidence. When a review asks for more proof, edit the body. Maintainer authorship does not skip the sections. A passing test is evidence about this source. Production activation is a separate record.

The org default procedure is `.github/org-consistency/skill/SKILL.md`. A stricter rule already in this file wins.
<!-- arc-forge-org-consistency:end -->
