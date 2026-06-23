"""Run the unittest suite with a hang watchdog.

If the suite does not finish within the timeout, dump every thread's stack to
stderr and abort. Used by the Windows CI step to diagnose deadlocks that
otherwise surface only as a non-descript STATUS_DLL_INIT_FAILED (0xC0000142).
"""

from __future__ import annotations

import faulthandler
import sys
import unittest

_TIMEOUT_SECONDS = 240


def main() -> int:
    faulthandler.enable()
    # On hang: dump all thread tracebacks, then hard-exit non-zero.
    faulthandler.dump_traceback_later(_TIMEOUT_SECONDS, exit=True)
    suite = unittest.TestLoader().discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
