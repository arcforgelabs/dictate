---
name: UI dependency lockfile updates
description: Cross-platform native binding metadata can be corrupted during UI lockfile refreshes.
---

When refreshing the nested UI lockfile, preserve native optional-package platform selectors even when the package versions do not change.

**Why:** Lockfile regeneration in this environment has shifted `libc` selectors onto unrelated Android, Darwin, and FreeBSD bindings while removing them from Linux GNU/musl bindings. A successful Linux x64 install and build cannot detect the resulting failures on other platforms.

**How to apply:** Compare unchanged packages' `cpu`, `os`, `libc`, and peer metadata with the prior lockfile, check updated packages against published metadata, and keep portable registry URLs. Then verify a locked install, UI tests, and build.