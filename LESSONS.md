# Lessons

## Whisper tail-hallucinations in push-to-talk

**Root cause**
- Whisper can decode trailing silence/ambient noise into plausible text, especially at the end of a
  recording.
- With `condition_on_previous_text=True`, the decoder conditions on its own prior output across
  segments and can "continue" into fabricated endings (hallucination chaining).
- Generous VAD padding (`speech_pad_ms`) and long silence windows (`min_silence_duration_ms`) feed
  more non-speech tail audio into the model, increasing the chance of hallucinations.

**Fix**
- In `src/dictate/stt/faster_whisper_backend.py`, pass:
  - `condition_on_previous_text=False` (prevents chaining on prior model output)
  - `no_speech_threshold=0.6` (suppresses low-confidence no-speech segments)
  - Tightened VAD: `speech_pad_ms=50` and `min_silence_duration_ms=300`

## Desktop packaging & CI (Tauri shell + frozen Python engine)

Hard-won, easy-to-trip-on details from building the `.deb`/`.rpm`/AppImage. Full
runbook: [docs/desktop-packaging.md](docs/desktop-packaging.md). The ones that
cost the most:

- **Freeze the engine PyInstaller `onefile`, not onedir** — `linuxdeploy` (AppImage)
  can't resolve PyInstaller's `$ORIGIN`-rpath mangled `_internal/*.so`
  (`ERROR: Could not find dependency: libnettle-<hash>.so`). Onefile = one ELF in
  the AppDir = no walk to fail. `.deb`/`.rpm` work either way.
- **Tauri icons must be RGBA PNG** or `generate_context!` panics (`assets/dictate.png`
  is `LA`).
- **AppImage in CI** needs `APPIMAGE_EXTRACT_AND_RUN=1` + `NO_STRIP=true` +
  `ARCH=x86_64` (no FUSE), and is **best-effort** — never let it block `.deb`/`.rpm`.
- **npm publish best-effort + idempotent `gh release create`** so neither blocks the
  installers.
- **Windows CI**: no `strftime("%-…")` (glibc-only); compare `str(Path(...))` not
  hard-coded `/`-paths. Tests use stdlib `unittest`.
- **Can't build the Tauri bundle in the dev sandbox** (no Rust/webkit-dev,
  `static.crates.io` blocked, sudo needs a password). Verify the freeze locally;
  iterate the bundle on CI via the manual `desktop-bundle.yml` workflow.
- **Version bump touches ~13 files + tests**, not just the three `release_check.py`
  checks — see the checklist in the runbook.

