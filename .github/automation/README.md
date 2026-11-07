# Native maintainer command reactions

The retained maintainer-command-reactions.yml uses the repository GITHUB_TOKEN
to acknowledge authorized maintainer commands. It does not merge, close,
publish, call an external hook or require an organization App credential.

Reaction logic is from openclaw/openclaw@5ff5fb278348bb6d2280bfbfb7e5cd3a66e74712,
MIT; the license is retained here. Org-App Barnacle/Labeler callers, their local
label-cap helper and Barnacle override are retired for the Linux-only personal
project. Central bot routing remains the fleet owner's separate responsibility.
