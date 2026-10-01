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
  must not block a dictation release or slow dictation down.
- **Not aligned:** conflicts with "Local only" or the "What we will not merge"
  list, or was started under a vision that has since changed. Recommend closing
  it with the `r: not-in-vision` label, quoting the conflicting line.

Product rejection stays a maintainer decision; reviewers recommend it.

## Records

GitHub issues and pull requests are the work record. Any remaining pointer to
Confluence, Jira (`OPS`, `DEL`) or the Assets registry is stale; strip it when
you touch the file.
