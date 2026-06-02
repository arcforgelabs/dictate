"""Frozen-engine entrypoint for the Dictate desktop bundle.

PyInstaller freezes this single script into one self-contained ``dictate-engine``
binary that ships inside the .deb / AppImage as the Tauri sidecar. It dispatches
to the right surface so one binary covers everything the packaged app needs:

    dictate-engine ui-server     -> the local control server (Settings window)
    dictate-engine --no-tray ... -> headless push-to-talk daemon
    dictate-engine doctor ...    -> diagnostics
    dictate-engine <args>        -> the normal dictate CLI

Keeping the dispatch here (rather than adding a subcommand to the CLI) means the
existing `dictate` and `dictate-ui-server` console scripts are unchanged.
"""

from __future__ import annotations

import sys


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "ui-server":
        from dictate.ui_server import main as server_main

        sys.argv = [sys.argv[0], *args[1:]]
        server_main()
        return 0

    from dictate.__main__ import main_with_logging

    return main_with_logging()


if __name__ == "__main__":
    raise SystemExit(main())
