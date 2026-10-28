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

## Changelog

`CHANGELOG.md` is an index of one file per release in `CHANGELOG/`, with
each release's contribution record again in `CHANGELOG/records/`. The
layout, formats and rules are openclaw/openclaw's split changelog. The
release owns these files:

- A normal pull request never edits `CHANGELOG.md`, `CHANGELOG/` or a
  release page in `docs/releases/`. Put the release-note text in the pull
  request: its title and its User Impact section.
- The release cut writes `CHANGELOG/<version>.md` from the pull requests
  in the release's range, edits the prose, and commits it with the version.
  Until Dictate's release train lands
  ([#145](https://github.com/arcforgelabs/dictate/issues/145)), the cut is
  the release's preparation pull request to `master`, the one pull request
  that writes these files (`docs/release-versioning.md`). The procedure is
  `.agents/skills/dictate-changelog-update/SKILL.md`.
- Nothing refuses a release without its file yet, and the GitHub Release
  does not take its notes from the file yet; both come with the release
  train (#145).
- A stable release covers everything since the previous stable release. A
  correction (`<version>-<n>`) covers the same range plus its fix. A beta
  covers everything since the release npm's `beta` tag selects before the
  beta publishes, in its own file. The old `unstable` npm shim tags are not
  releases and get no file.
- A release file has Highlights, Changes and Fixes, then a complete
  contribution record that lists every pull request in the range once:
  `- **PR #N** Related #I. Thanks @a and @b.` A prose bullet names its pull
  requests as `(#N, #M)` and keeps every thanks from their rows. `feat`,
  `improve` and `fix` pull requests go in the prose; `docs`, `chore`,
  `refactor`, `test`, `ci`, `build` and `style` go only in the record,
  unless the title marks a breaking change with `!`.
- A stable release aims for 5 to 8 highlights and has at most 8; a beta has
  0 to 8. The 5 is a guideline, not a release gate: a small stable patch
  release ships with the user stories it has (as OpenClaw's patch releases
  do), and never with invented ones.
- Thanks go to the pull request's author, its co-authors and the people who
  reported the issues it closes (`Closes #N`, `Fixes #N`, `Resolves #N`).
  Never to bots, to Claude or Codex, to the organization or to the
  maintainer.
- CI runs `npm run changelog:check` (`scripts/release/changelog.mjs
  check`), which holds the format rules; `verify` holds the rules that need
  git and GitHub. `CHANGELOG/Unreleased.md` stays empty.

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
