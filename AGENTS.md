# Dictate

Read `VISION.md` before changing product behaviour, and before reviewing an
issue or pull request. It owns product scope: what Dictate is, the order of
work, and the "What we will not merge" list. `README.md` indexes the rest of
the docs.

The shared rules are referenced below; this repo's own rules are in Dictate safeguards, at the end.

<!-- arc-forge-org-consistency:start -->
Read the shared Arc Forge instructions before work:
https://github.com/arcforgelabs/tools/blob/main/docs/AGENTS.shared.md

Optional local source: ~/repos/tools/docs/AGENTS.shared.md.
Verify that the local checkout has the origin arcforgelabs/tools before use.
Do not copy the shared rules here.
Keep repository-specific safeguards and document references outside this block.

Common agent workflows: https://github.com/openclaw/agent-skills.
Product repositories own their product-specific skills.
Reusable release workflows: https://github.com/openclaw/release-workflows.
<!-- arc-forge-org-consistency:end -->

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
