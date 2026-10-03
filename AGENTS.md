# Dictate

Read `VISION.md` before changing product behaviour, and before reviewing an
issue or pull request. It owns product scope: what Dictate is, the order of
work, and the "What we will not merge" list. `README.md` indexes the rest of
the docs.

## Reviewing

Judge every issue and pull request against `VISION.md`, and say which line it
fits or conflicts with. Three outcomes:

- **Aligned, current:** dictation work, or anything the "Order of work" puts
  first.
- **Aligned, later:** meeting and long-recording work. Fine to keep open; it
  must not block a dictation release or slow dictation down, and it ships only
  in Dictate Beta, never in the stable app. Until that split lands (#131),
  fixes to the Meeting code already in the tree count here too.
- **Not aligned:** conflicts with "Local only" or the "What we will not merge"
  list, or was started under a vision that has since changed. Recommend closing
  it with the `r: not-in-vision` label, quoting the conflicting line.

Product rejection stays a maintainer decision; reviewers recommend it.

## Records

GitHub issues and pull requests are the work record. Any remaining pointer to
Confluence, Jira (`OPS`, `DEL`) or the Assets registry is stale; strip it when
you touch the file.

<!-- arc-forge-org-consistency:start -->
## Pull requests

Use `.github/pull_request_template.md`. Keep these sections current in the pull request body:

- What Problem This Solves
- Why This Change Was Made
- User Impact
- Evidence

Evidence names the command, the commit, the result, and what was not run. A screenshot is the real product, with the viewport and whether the data was synthetic or live. If the proof could not be run, name the gap in Evidence. When a review asks for more proof, edit the body. Maintainer authorship does not skip the sections. A passing test is evidence about this source. Production activation is a separate record.

The org default procedure is `.github/org-consistency/skill/SKILL.md`. A stricter rule already in this file wins.
<!-- arc-forge-org-consistency:end -->
