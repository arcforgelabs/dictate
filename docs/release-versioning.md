# Release Versioning

Dictate uses calendar versioning for public releases:

```text
YYYY.M.D
```

The release version is the calendar date of the release without zero-padding month or day. A release on May 18, 2026 is:

```text
2026.5.18
```

Python package metadata uses the same PEP 440-compatible version:

```text
2026.5.18
```

The app reports the public release version through:

```bash
dictate --version
```

Generate versions with:

```bash
python scripts/calver.py --date 2026-05-18
python scripts/calver.py --date 2026-05-18 --format pep440
```

Release tags and GitHub milestones should use the public version with a leading `v`, for example:

```text
v2026.5.18
```
