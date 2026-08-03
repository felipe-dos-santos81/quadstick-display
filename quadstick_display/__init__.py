"""Quadstick Display package.

Re-exports the pure domain model and exposes the Flask application
factory ``create_app``. The factory is resolved lazily so that importing
the package (or its model/view/controller modules) never pulls Flask,
pandas, or Raspberry Pi packages into non-web contexts.
"""

from quadstick_display.model import (
    Binding,
    InvalidProfile,
    InvalidProfileName,
    Profile,
    ProfileNotFound,
    ProfileStore,
    parse_quadstick_csv,
)

__all__ = [
    "Binding",
    "InvalidProfile",
    "InvalidProfileName",
    "Profile",
    "ProfileNotFound",
    "ProfileStore",
    "create_app",
    "parse_quadstick_csv",
]


def __getattr__(name):
    if name == "create_app":
        from quadstick_display.web import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
