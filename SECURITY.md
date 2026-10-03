# Security Policy

If you believe you found a security issue in Dictate, report it privately first.

Use GitHub private vulnerability reporting for this repository when it is available. If private reporting is not available, open a public issue that only asks for a disclosure contact and does not include exploit details, secrets, API keys, logs containing credentials, or private user vocabulary.

## What to Include

- Dictate version and commit SHA when possible.
- Operating system and install path.
- Reproduction steps against the latest release or current `master`.
- The impact and why it crosses a real security boundary.
- A focused fix or mitigation if you have one.

## Do Not Post Publicly

- Credential material, such as a Hugging Face token.
- Personal hotwords, private names, customer terms, or sensitive dictation text.
- Full logs unless you have checked and removed secrets.
- Exploit details for an unpatched issue.

Dictate is a local desktop app. A trusted local user intentionally installing, configuring, or running local commands is usually not a vulnerability by itself. Reports are most useful when they show an unintended path from untrusted input to credential exposure, command execution, data exposure, privilege escalation, or update/install compromise.

## Accepted Risks (tracked)

None. The last tracked advisory, the transformers `Trainer` RCE
(GHSA-69w3-r845-3855), came in only through the experimental `[sortformer]`
Meeting extra, which was removed with Meeting capture (#140). torch,
transformers and NLTK are no longer dependencies.
