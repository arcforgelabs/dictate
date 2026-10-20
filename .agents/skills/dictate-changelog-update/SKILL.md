---
name: dictate-changelog-update
description: Write a Dictate release's changelog file (CHANGELOG/<version>.md, its record in CHANGELOG/records/ and its docs page in docs/releases/) from the history since the previous release. Use when cutting a beta or stable release, or when asked to write or fix release notes.
---

# Dictate changelog update

This is openclaw/openclaw's `openclaw-changelog-update` skill, with
Dictate's names, copied from arcforgelabs/flow at 1148280 (flow#197).
`CONTRIBUTING.md` holds the rules; `scripts/release/changelog.mjs` holds
the tool, the format check (`check`) and the history check (`verify`).

## When

At the release cut, before the release is tagged. Until Dictate's release
train lands ([#145](https://github.com/arcforgelabs/dictate/issues/145)),
the cut is the release's preparation pull request to `master` (the version
bump, `docs/release-versioning.md`): it is the one pull request that writes
these files. Never in a feature pull request. Each beta gets its own file
(`CHANGELOG/<version>-beta.<n>.md`), never a copy of the stable file; the
stable release gets a new, cumulative file, and a correction
(`CHANGELOG/<version>-<n>.md`) the same range plus its fix. The old
`unstable` npm shim tags (`v<version>-unstable.<run>.<attempt>`) are not
releases and get no file.

## Inputs

- Stable base: the newest stable release tag older than the version, on
  any branch. When it is not in the target's history (it shipped from its
  own release branch), the range starts at their merge base and leaves out
  the pull requests that release already shipped, picks included.
- Beta base: the version npm's `beta` tag selects before the beta
  publishes. `draft` reads it with `npm view @arcforgelabs/dictate
  dist-tags.beta`. If npm already selects this beta or a newer one, pass the
  tag you captured before publishing with `--base`.
- Target: the commit the release will tag. Until #145, that is
  `origin/master` as the preparation pull request branches from it; the
  preparation pull request itself is not in the record. The record's target
  may be an older commit of that history; any pull request merged after it
  makes `verify` fail until you draft again.

## Steps

1. Get the full history. A shallow clone gives a short range, and the tool
   refuses it:

   ```bash
   git fetch --unshallow --tags origin   # or: git fetch --tags origin
   ```

2. Draft the section and its manifest. `draft` reads each pull request's
   author, commits and closed issues from GitHub (`gh api`):

   ```bash
   node scripts/release/changelog.mjs draft --version <version> \
     --target origin/master --output /tmp/section.md --manifest /tmp/manifest.json
   ```

   The draft has every `feat`, `improve` and `fix` pull request under
   Changes or Fixes, the first eight of them as Highlights, and the complete
   contribution record: every pull request in the range once, as
   `- **PR #N** Related #I. Thanks @a and @b.` The manifest also lists the
   direct commits. They are editorial input; they get no row. An older
   pull request merged with a merge commit (`Merge pull request #N from
   ...`) counts as its title and `(#N)`, as a squash would.

3. Read the manifest, then edit the prose, not the record:
   - Highlights: 1 to 8 bullets for a stable release, 0 to 8 for a beta.
     One user story per bullet, in one sentence, with every pull request
     that tells it: `- Text. (#N, #M) Thanks @a.` Leave out tests, CI,
     refactors and docs unless the outcome is a material install, update or
     privacy change.
   - Changes: new capabilities and behaviour changes. Fixes: user-facing
     fixes first. Group pull requests that tell one story into one bullet.
   - A bullet that names a pull request keeps every thanks from its record
     row. Issues stay inline as `#N`.
   - Put the user-visible fixes first: privacy and data safety, then
     dictation, then install and update, then screens. Drop release-process
     words such as "release 2026.10.3".
   - Never thank bots, Claude, Codex, the organization or the maintainer.
   - No customer, lab, practice or person names. The repository is public.

4. Save it, and check it against history and GitHub:

   ```bash
   node scripts/release/changelog.mjs write --version <version> --file /tmp/section.md
   node scripts/release/changelog.mjs verify --version <version> --target origin/master
   npm run changelog:check
   ```

5. Commit `CHANGELOG/<version>.md`, `CHANGELOG/records/<version>.md`,
   `CHANGELOG.md` and, for a stable release or a correction,
   `docs/releases/<version>.md` together in the preparation pull request.
   `write` writes the docs page from the file; never edit the page by hand.
   After the merge and the tag, `verify --version <version> --target <the
   record's target>` still passes; without `--target` it checks through the
   tag, which adds the preparation pull request.

6. The release workflow does not use the file yet (#145). To make the
   GitHub Release body the notes by hand, and check it:

   ```bash
   node scripts/release/changelog.mjs notes --version <version> > notes.md
   gh release edit v<version> --notes-file notes.md
   node scripts/release/changelog.mjs verify --version <version> --check-github
   ```

`node scripts/release/changelog.mjs notes --version <version>` prints the
GitHub Release body for that version: the whole section, or, past GitHub's
125,000-character limit, the prose and a link to the tag's record file.
`verify` keeps GitHub's answers in `.git/dictate-changelog/`;
`--refresh-github-snapshot` asks again.

## Docs page and roster

OpenClaw's post-release docs route, with Dictate's names:

- The docs page. `write` and `index` write `docs/releases/<version>.md` for
  each stable release and correction from its file: the prose for readers,
  with the pull requests, issues and people as links, the numbers, and a
  link to the record. `check` refuses a page that is not the file's page.
  The page reaches `master` with the file; Docs Sync Publish mirrors it to
  `arcforgelabs/docs`, which lists every release with the highest stable as
  latest (https://arcforgelabs.github.io/docs/dictate/releases/).
- The roster. After the docs site serves the page,
  `node scripts/release/changelog.mjs thanks --version <version>` prints the
  GitHub Release body that replaces the notes: the version, its pull
  requests, direct commits and contributors, the docs, Raw changelog and
  record links, and one alphabetical roster of every person GitHub credits
  on its pull requests and direct commits (authors, co-authors, issue
  reporters). The maintainer is in the roster; bots, agents and the
  organization are not. The published body's `### Release verification`
  section stays. Check it with `verify --check-github --post-docs`. Never
  retag, rebuild or publish again to change the body.

## Differences from OpenClaw

- A stable release has 1 to 8 highlights, not OpenClaw's 5 to 8. Reason:
  Arc Forge's stable releases are often small, and a highlight must be a
  real user-facing change; the maintainer chose this on 20 Oct 2026 rather
  than pad highlights with internal work.
- Release train: not copied yet, planned in
  [#145](https://github.com/arcforgelabs/dictate/issues/145). Dictate's
  build is Python and desktop installers (`docs/release-versioning.md`), so
  Flow's release branch, prepare, publish and closeout workflows do not fit
  as they are. Until then the files go through the release's preparation
  pull request to `master`, nothing refuses a release without its file, the
  release workflow still writes its own GitHub Release body, and the
  `thanks` roster is applied by hand. OpenClaw commits the files on the
  release branch and never through a pull request.
- The old `unstable` npm shim tags (`v<version>-unstable.<run>.<attempt>`)
  are skipped: they are test builds of a branch, not releases, and
  `docs/RELEASING.md` replaces them with betas. The tag parser does not
  accept them, so they are never a range's base and get no file.
- Older corrections were `-K` repackages (`2026.9.25-1` to `-4`). They use
  OpenClaw's correction rule as they are: each covers the same range as its
  stable release, so its file repeats that release's notes and adds its own.
- Pull requests merged before Dictate squashed them have a merge commit
  (`Merge pull request #N from <branch>`). The tool reads that commit as
  its pull request, from the title in the merge commit's body
  (`mergedSubject` in `scripts/release/changelog.mjs`). OpenClaw and Flow
  squash every pull request, so they need no such rule.
- The links on the docs pages and in `CHANGELOG.md` name `master`, the
  default branch, where Flow's name `main`.
- The docs page is written from the changelog file at the cut, and the file
  stays the one source. OpenClaw writes its docs page by hand in a separate,
  approved docs pull request after the release, then turns the changelog
  file into a flat copy of the page (`changelog:from-docs`). Reason: Flow's
  route, copied here, keeps the page, the file and the release body in step
  from one source.
- OpenClaw's post-docs body renderer is in its private release tooling.
  Dictate's `thanks` body follows the public text of OpenClaw's skill
  (numbers, Raw changelog and docs links, the roster, the verification
  section); its exact layout is Flow's.
- Docs pages exist for stable releases and corrections only, as OpenClaw's
  `docs/releases/` has no beta page.
- The back-filled releases (2026.5.18 to 2026.10.2) keep the hand-written
  text of the old `CHANGELOG.md`, sorted into Highlights, Changes and Fixes.
  Several have fewer than 5 highlights because the old text has fewer items;
  `verify` reports them, and nobody padded them.
