---
name: UI dependency lockfile updates
description: Replit npm quirks encountered while refreshing the nested UI dependency lockfile.
---

When refreshing the UI lockfile in this environment, npm 10.9.4 can fail with an Arborist `edgesOut` TypeError while resolving Vite/Vitest optional peers. npm 11 succeeded on the available Node 22 runtime.

**Why:** Using `--legacy-peer-deps` avoids that resolver path but removes `libc` selectors from optional native-package entries, and Replit's configured registry can write internal mirror URLs into the lockfile.

**How to apply:** Prefer a normal clean install from the generated lockfile; preserve optional-package `libc` metadata and canonical `registry.npmjs.org` resolved URLs, then run the audit, UI tests, and build.