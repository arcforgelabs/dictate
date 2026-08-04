# Known Issues

Open defects we have accepted for now, with enough detail to fix them later
without re-deriving the diagnosis. Remove an entry when it is resolved.

## Linux `stable` install/update via npm fails (accepted 2026-08-04)

**Symptom.** On Linux, `npx @arcforgelabs/dictate install` (and the equivalent
update path) fails on the `stable` channel. `unstable` is unaffected.

**Cause.** `install.sh` installs the engine from its own directory:

```sh
PIP_TARGET="$SCRIPT_DIR"          # install.sh:189
uv pip install "$PIP_TARGET" ...  # install.sh:240
```

That requires `pyproject.toml` and `src/` to be present inside the published npm
package. The published stable tarball does not contain them:

| dist-tag   | version                  | files | Python payload |
| ---------- | ------------------------ | ----- | -------------- |
| `unstable` | 2026.7.4-unstable.63.1   | 131   | 69 files       |
| `latest`   | 2026.7.4                 | 19    | none           |

`package.json` correctly lists `pyproject.toml` and `src/**/*.py` under `files`,
but that fix (`fc993f1299 "Include Linux source in npm shim"`) landed *after*
`9c090267ff "Release 2026.7.4"`. The stable tarball on the registry predates it
and was never rebuilt.

Previously the GitHub tag archive masked this. The repository is now private, so
that fallback is gone and the failure is user-visible.

**Fix.** Cut a new stable release so the `latest` dist-tag carries a package
built with the current `files` list. Then verify the artifact directly — do not
trust the workflow exit code:

```sh
curl -sL "$(npm view @arcforgelabs/dictate dist.tarball)" | tar tz | grep -c 'src/.*\.py'
```

Expect a non-zero count. npm publishes in `release.yml` fail silently (see
`npm view @arcforgelabs/dictate dist-tags`, which lagged GitHub Releases by five
builds — 63.1 vs 68.1 — when this was written), so the verification step is
load-bearing, not optional.

**Not affected.** Windows (Microsoft Store), existing installs already on disk,
and update *checks* — those resolve versions from the npm registry's dist-tags
metadata, which needs no repository access.
