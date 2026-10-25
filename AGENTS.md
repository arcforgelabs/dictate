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
## Pull requests

Use `.github/pull_request_template.md`. Keep these sections current in the pull request body:

- What Problem This Solves
- User Impact
- Why This Change Was Made
- Evidence

Evidence names the command, the commit, the result, and what was not run. A screenshot is the real product, with the viewport and whether the data was synthetic or live. If the proof could not be run, name the gap in Evidence. When a review asks for more proof, edit the body. Maintainer authorship does not skip the sections. A passing test is evidence about this source. Production activation is a separate record.

The org default procedure is `.github/org-consistency/skill/SKILL.md`. A stricter rule already in this file wins.
<!-- arc-forge-org-consistency:end -->

## Cursor Cloud specific instructions

Cloud Agents get Python 3.12, the Quiet Console, and the Linux desktop-shell toolchain. `uv` is on `/usr/local/bin`. Rust stable is the toolchain Tauri 2.12 needs (the base image's 1.83 is too old).

- Engine and tests: `uv run python -m unittest discover -s tests`, `uv run dictate --version`, `uv run dictate doctor --quick`. Linux install uses `uv sync --frozen --extra x11`.
- UI: `npm test --prefix ui` and `npm run build --prefix ui`. On boot the dev server listens at `http://127.0.0.1:5173` (`npm run dev --prefix ui -- --host 0.0.0.0 --port 5173`). With no `ui-server` handshake this is the in-browser mock: Start recording, pause, Finish note. Do not start a second Vite server on that port.
- Control-server smoke, isolated from the user config: `./scripts/ui-server-smoke.sh .venv/bin/python`.
- Clipboard tests against X: `xvfb-run -a uv run python -m unittest -v tests.test_clipboard_linux`.
- Desktop shell: `cargo test --manifest-path ui-shell/src-tauri/Cargo.toml`. Install creates `ui-shell/src-tauri/engine/dictate-engine` when that placeholder is missing, which is what the bundle resource glob expects. There is no microphone in this environment; `dictate doctor --quick` warns about that and still reports healthy.
