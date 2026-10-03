# Security Policy

If you believe you found a security issue in Dictate, report it privately first.

Do not open a public issue or pull request that discloses an unpatched vulnerability, exploit path, secret, or security-sensitive proof of concept.

## Reporting

Submit a private [GitHub Security Advisory](https://github.com/arcforgelabs/dictate/security/advisories/new) for this repository. If you cannot use it, open a public issue that only asks for a disclosure contact and contains no details.

Useful reports include:

- Dictate version and commit SHA,
- operating system, version and architecture, and how Dictate was installed (Microsoft Store, MSI, `.deb`, bootstrap script, or source),
- the affected component or file path,
- reproduction steps against the latest release or current `master`,
- the actual impact and which trust boundary below it crosses,
- a suggested fix or mitigation, when practical.

Reports without reproduction steps and demonstrated impact may be deprioritized.

## Do Not Post Publicly

- Credential material, such as a Hugging Face token.
- Personal hotwords, private names, customer terms, or sensitive dictation text.
- Full logs, unless you have checked them and removed secrets and dictated text.
- Exploit details for an unpatched issue.

## Scope

Security-relevant surfaces in this repository include:

- the local-only guarantee: audio and transcripts must not leave the device (proved in CI by `.github/workflows/privacy-proof.yml`),
- microphone capture, the push-to-talk shortcut, and typing text into the focused app,
- the local UI server (`src/dictate/ui_server.py`): its `127.0.0.1` binding, the per-run token, and the handshake file `ui-server.json`,
- local dictation history, hotwords and configuration under the user's `dictate` config and data directories,
- the speech model download from Hugging Face,
- update checks and downloads from GitHub Releases, including SHA-256 verification (`src/dictate/update_status.py`),
- installers, updaters and uninstallers: the MSI, MSIX, `.deb`, the `install*.ps1` / `install*.sh` scripts, and the npm bootstrap served through jsDelivr,
- GitHub Actions, the self-hosted Windows release-gate runner, npm publishing, and Microsoft Store submission (see `docs/deployment-security.md`).

## Out of Scope

The following are usually out of scope:

- vulnerabilities in upstream Windows, Linux desktops, WebView2/WebKitGTK, Tauri, ONNX Runtime, `huggingface_hub`, or other dependencies without reachable impact through Dictate,
- reports that need prior write access to trusted local state, such as the user's `dictate` config or data directories, installed binaries, or shell profiles,
- another process running as the same OS user reading Dictate's local files or the UI token: that user is already trusted,
- the focused app receiving the text Dictate types into it, which is the product working as intended,
- Windows warning that an unsigned staging MSI is from an untrusted publisher, which is documented and expected,
- insecure local administration or shared multi-user machines where the OS trust boundary is already lost,
- scanner-only findings without a working reproduction and demonstrated Dictate impact.

## Trust Boundaries

Dictate assumes that the local OS account and machine running it are trusted.

- Configuration, history, hotwords and the UI token are local user data.
- Dictate runs with the current user's privileges.
- Nothing binds beyond `127.0.0.1`, and every route that changes state requires the per-run token.
- Untrusted inputs are web content that can reach loopback, downloaded model files, and downloaded update payloads.

Reports should show how one of those untrusted inputs crosses into code execution, data exposure, persistence, or an install or update compromise.

## Accepted Risks (tracked)

None. The last tracked advisory, the transformers `Trainer` RCE
(GHSA-69w3-r845-3855), came in only through the experimental `[sortformer]`
Meeting extra, which was removed with Meeting capture (#140). torch,
transformers and NLTK are no longer dependencies.
