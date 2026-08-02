"""Compatibility entrypoint for the Quadstick display web service.

The shipped systemd unit runs ``python qs_display.py httpd``. The
application now lives in the ``quadstick_display`` package; this shim
only preserves the legacy invocation contract.
"""

import sys

from quadstick_display.__main__ import HTTP_PORT, main

__all__ = ["HTTP_PORT", "main"]


if __name__ == "__main__":
    main(sys.argv[1:])
