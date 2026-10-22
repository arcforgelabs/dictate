# Contributing

Contributions are welcome.

Read [`VISION.md`](VISION.md) first. Dictate is local-only voice-to-text:
dictation now, meetings later. Changes outside that, including anything on its
"What we will not merge" list, will be closed however well they are built. If
you think the vision should change, open an issue about the vision first.

By opening a pull request or submitting a patch, you confirm that:

- You have the right to submit the contribution.
- Your contribution does not knowingly include secrets, private credentials, or
  material you are not allowed to publish.
- Your contribution is provided under the MIT License.

Keep changes focused, include tests when behavior changes, and do not include
personal hotwords, private dictation text, or API keys in examples, logs, or
fixtures.

## Agent rules

`AGENTS.md` holds the rules for coding agents. `CLAUDE.md` is a git symlink to
it so Claude Code reads the same file; edit `AGENTS.md`, never `CLAUDE.md`.

On Windows, Git only creates the link when `core.symlinks` is on, which needs
Developer Mode or an elevated shell. Without it, `CLAUDE.md` is checked out as a
plain file holding the text `AGENTS.md`, and Claude Code does not see the
rules. Clone with `git clone -c core.symlinks=true`, or fix an existing clone
with `git config core.symlinks true`, then delete `CLAUDE.md` and run
`git checkout -- CLAUDE.md`.

<!-- arc-forge-org-consistency:start -->
## Issue, PR, and contact routing

This follows upstream OpenClaw's routing. Start here before you create a GitHub item:

| Situation | Use | Required evidence |
| --- | --- | --- |
| Bug, regression, crash or wrong behaviour | Bug report form | Repro steps, expected and actual behaviour, version, OS, model and provider route when relevant, logs or screenshots, impact |
| Wrong, missing or contradictory docs | Docs bug report form | Docs path or URL, verification steps, expected and actual content, impact, evidence |
| New capability or improvement | Feature request form | Problem, proposed solution, alternatives, impact, examples, whether you will open the PR |
| Security issue | This repo's `SECURITY.md`; without one, the [Arc Forge security policy](https://github.com/arcforgelabs/business/blob/master/SECURITY.md) | Never paste a credential, in full or in part |
| Defect in OpenClaw itself | The upstream repo's own forms and `CONTRIBUTING.md` | What upstream asks for, in its language (American English for OpenClaw) |
| PR for an existing or new issue | `.github/pull_request_template.md` | Visible `Closes #<issue>` or `Related: #<issue>`, then the four sections below |

The forms in `.github/ISSUE_TEMPLATE/` are copies of upstream OpenClaw's. Answer every field from observed evidence. Where the evidence does not answer a field, write exactly `NOT_ENOUGH_INFO`. File one issue per report, and reuse an open issue rather than file a duplicate. Without the web form (for example `gh issue create`), use each field label as a `###` heading in the body.

For agent-authored or non-trivial work, create or reuse the issue first, then open the PR against it. Do not tag people to route work; the forms and labels do that.

## Pull request body

Use `.github/pull_request_template.md` and keep the body current:

- **What Problem This Solves** — the concrete problem and when it happens.
- **User Impact** — what someone can now do, or a plain statement that there is no user-visible change.
- **Why This Change Was Made** — the shipped solution and any boundary that matters.
- **Evidence** — the command, commit, result, and what was not run. Screenshots show the real product. Placeholder text does not count.

Edit the pull request body when someone asks for more proof. A review comment can point at that edit. The body stays the record. Maintainer authorship does not remove this requirement.
<!-- arc-forge-org-consistency:end -->
