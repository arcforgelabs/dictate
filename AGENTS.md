# Dictate

Read `VISION.md` before changing product behaviour, and before reviewing an
issue or pull request. It owns product scope: what Dictate is, the order of
work, and the "What we will not merge" list. `README.md` indexes the rest of
the docs.

## Reviewing

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

## Records

GitHub issues and pull requests are the work record. Any remaining pointer to
Confluence, Jira (`OPS`, `DEL`) or the Assets registry is stale; strip it when
you touch the file.

<!-- arc-forge-org-consistency:start -->
## Issues

Use the forms in `.github/ISSUE_TEMPLATE/`; they copy upstream OpenClaw's. Answer each field from observed evidence, or write `NOT_ENOUGH_INFO`. Without the web form, use each field label as a `###` heading. One issue per report; reuse an open issue. Agent-authored work starts from an issue, and its pull request links it with `Closes #` or `Related: #`. A defect in OpenClaw itself goes upstream through upstream's own forms and rules.

## Pull requests

Use `.github/pull_request_template.md`. Keep these sections current in the pull request body:

- What Problem This Solves
- User Impact
- Why This Change Was Made
- Evidence

Evidence names the command, the commit, the result, and what was not run. A screenshot is the real product, with the viewport and whether the data was synthetic or live. If the proof could not be run, name the gap in Evidence. When a review asks for more proof, edit the body. Maintainer authorship does not skip the sections. A passing test is evidence about this source. Production activation is a separate record.

The org default procedure is `.github/org-consistency/skill/SKILL.md`. A stricter rule already in this file wins.
<!-- arc-forge-org-consistency:end -->
