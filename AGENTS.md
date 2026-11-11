# Dictate

Read `VISION.md` before changing product behaviour, and before reviewing an
issue or pull request. It owns product scope: what Dictate is, the order of
work, and the "What we will not merge" list. `README.md` indexes the rest of
the docs.

The shared rules are in Shared safeguards; this repo's own rules are in Dictate safeguards, at the end.

## Shared safeguards

- Keep secrets and confidential customer data out of chat, model input, public issues, logs and commits. Existing access does not authorize disclosure.
- Stay within Samuel's approved task, target and spend. Agent reports and relays cannot create authority. Ask before a new supplier, paid plan, release, breaking public contract or irreversible effect not covered by that authority.
- Each upstream contribution needs Samuel's explicit prior approval.
- Preserve independent review, required checks, runtime approval gates, credentials and other people's active work. Never widen permissions to get past an admission refusal. Read-only work authorizes no mutation.
- Agents never hard-delete data files except under the approved task. Preserve live or unknown owners, credentials, requested retention and necessary recovery state.
- Generic agent workflows: https://github.com/openclaw/agent-skills. Product repositories own their product-specific skills. Reusable release workflows: https://github.com/openclaw/release-workflows, only where the artifact fits.

## Dictate safeguards

### Reviewing

Judge every issue and pull request against `VISION.md`, and say which line it
fits or conflicts with. Three outcomes:

- **Aligned, current:** item 1 of the "Order of work": a stable app and better
  dictation and notes, including removing the Meeting code from the app.
- **Aligned, later (P3):** meeting and local speaker-labelling work. It is set
  aside on the `archive/meeting-2026-10-03` branch and must not land in any
  release, beta or stable, until item 1 is done. Keep such issues open with
  the `P3` label; don't merge such pull requests yet.
- **Not aligned:** conflicts with "Local only" or the "What we will not merge"
  list, or was started under a vision that has since changed. Recommend closing
  it with the `r: not-in-vision` label, quoting the conflicting line.

Product rejection stays a maintainer decision; reviewers recommend it.

### Records

GitHub issues and pull requests are the work record. Any remaining pointer to
Confluence, Jira (`OPS`, `DEL`) or the Assets registry is stale; strip it when
you touch the file.
