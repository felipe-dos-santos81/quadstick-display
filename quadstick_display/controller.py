"""Display seam: panel geometry, frames, device protocol, and the controller.

This module hosts the types shared between the view (which produces
``DisplayFrame`` images), the hardware adapter (which consumes them), and
``DisplayController`` (which owns the serialized display transaction).
It must stay importable without Raspberry Pi packages; the view is only
referenced under ``TYPE_CHECKING`` so this module never imports it at
runtime (the view already imports the seam from here).

``DisplayController`` runs the atomic load-render-show-status transaction:
one lock spans the whole transaction so concurrent requests can never
interleave panel writes, and ``DisplayStatus.current_profile`` changes only
after the panel accepts a frame.
"""
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from PIL import Image

from quadstick_display.model import (
    InvalidProfile,
    InvalidProfileName,
    ProfileNotFound,
    ProfileStore,
)

if TYPE_CHECKING:
    from quadstick_display.view import ProfileRenderer


@dataclass(frozen=True)
class DisplaySize:
    """Logical panel geometry in production orientation.

    The Waveshare 4.2-inch panel is wired so that the logical width is the
    driver's ``height`` and the logical height is the driver's ``width``;
    ``hardware.WaveshareDisplay`` performs that swap, so the rest of the
    application always works in this logical orientation.
    """

    width: int
    height: int


@dataclass(frozen=True)
class DisplayFrame:
    """The two monochrome planes sent to the e-paper panel.

    Plane modes and sizes are NOT guaranteed to be homogeneous. Profile
    frames from ``ProfileRenderer.render`` are both mode ``'1'`` images at
    the logical ``DisplaySize``, but the startup frame's black plane is the
    raw logo asset (300x400, mode ``'L'``) while its red plane is mode
    ``'1'`` at the logical size. ``DisplayDevice`` implementations hand
    each plane to the driver as-is, exactly as the legacy pipeline did;
    normalizing the startup planes is deliberately out of scope (M2
    caveat carried through M3).
    """

    black: Image.Image
    red: Image.Image


@runtime_checkable
class DisplayDevice(Protocol):
    """The minimal hardware seam: size, one-time init, and frame output."""

    @property
    def size(self) -> DisplaySize: ...

    def initialize(self) -> None: ...

    def show(self, frame: DisplayFrame) -> None: ...


@dataclass(frozen=True)
class DisplayStatus:
    """Observable display state: the last shown profile and last error."""

    current_profile: str | None
    last_error: str | None


class DisplayFailure(RuntimeError):
    """The physical display rejected a frame."""


# Model errors that propagate out of ``DisplayController.show_profile``
# unchanged (typed errors); any other failure in the render/show half of
# the transaction is wrapped in ``DisplayFailure``.
_MODEL_ERRORS = (InvalidProfile, InvalidProfileName, ProfileNotFound)


class DisplayController:
    """Owns the atomic display transaction and the observable display state.

    ``show_profile`` holds one lock across the complete
    load-render-show-status transaction, so concurrent requests are
    serialized and panel writes can never interleave. The status is
    published only after ``DisplayDevice.show`` returns: a failed load,
    render, or write records ``last_error`` and leaves ``current_profile``
    untouched.

    Model errors (``InvalidProfileName``, ``ProfileNotFound``,
    ``InvalidProfile``) propagate typed; renderer and display errors are
    wrapped in ``DisplayFailure`` with exception chaining.
    """

    def __init__(
        self,
        store: ProfileStore,
        renderer: 'ProfileRenderer',
        device: DisplayDevice,
    ):
        self._store = store
        self._renderer = renderer
        self._device = device
        self._lock = threading.Lock()
        self._status = DisplayStatus(current_profile=None, last_error=None)

    @property
    def status(self) -> DisplayStatus:
        """The last published status; an immutable snapshot."""
        return self._status

    def show_profile(self, name: str) -> DisplayStatus:
        """Load, render, and show ``name``; return the new status.

        Typed model errors (``InvalidProfileName``, ``ProfileNotFound``,
        ``InvalidProfile``) propagate unchanged, and renderer or hardware
        errors are raised as ``DisplayFailure`` (chained from the cause);
        both record ``last_error`` and preserve ``current_profile``.
        Unexpected store-load errors (e.g. an ``OSError`` from the store
        that is not a typed model error) propagate unchanged *without*
        recording ``last_error``.
        """
        with self._lock:
            try:
                profile = self._store.load(name)
            except _MODEL_ERRORS as exc:
                self._record_error(str(exc))
                raise
            try:
                frame = self._renderer.render(profile, self._device.size)
                self._device.show(frame)
            except Exception as exc:
                failure = DisplayFailure(
                    f'unable to display profile {name!r}: {exc}'
                )
                self._record_error(str(failure))
                raise failure from exc
            self._status = DisplayStatus(current_profile=name, last_error=None)
            return self._status

    def _record_error(self, message: str) -> None:
        """Record a failure message without changing the current profile."""
        self._status = DisplayStatus(
            current_profile=self._status.current_profile,
            last_error=message,
        )
