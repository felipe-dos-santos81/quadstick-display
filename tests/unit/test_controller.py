"""Unit tests for the display controller (quadstick_display.controller).

Pins the M3 transaction contract: one lock spans the complete
load-render-show-status transaction so concurrent requests can never
interleave panel writes; ``current_profile`` changes only after the panel
accepts a frame; model errors propagate typed (``InvalidProfileName``,
``ProfileNotFound``, ``InvalidProfile``); renderer and display errors are
wrapped in ``DisplayFailure`` with exception chaining; failures record
``last_error`` without changing ``current_profile``.
"""

import dataclasses
import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/

from fakes import PRODUCTION_SIZE, FakeDisplay

from quadstick_display.controller import (
    DisplayController,
    DisplayFailure,
    DisplayFrame,
    DisplayStatus,
)
from quadstick_display.model import (
    Binding,
    InvalidProfile,
    InvalidProfileName,
    Profile,
    ProfileNotFound,
    ProfileStore,
)
from quadstick_display.view import ProfileRenderer

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = REPO_ROOT / "resources"


def csv_text(pairs, title="Some Game"):
    """Minimal valid Quadstick CSV export text (mirrors the model tests)."""
    rows = [
        f"QuadStick Configuration,Version 1.5,HASH,{title}",
        "Profile Name,,Inputs",
        "some.csv,,Normal",
        "Output or Function,Function,usb",
    ]
    rows += [f"{command},normal,{qs_input}" for command, qs_input in pairs]
    return "\n".join(rows) + "\n"


def blank_frame():
    return DisplayFrame(
        black=Image.new("1", (400, 300), 255),
        red=Image.new("1", (400, 300), 255),
    )


class StubRenderer:
    """Renderer double: records (profile, size) calls, returns a fixed frame."""

    def __init__(self, frame=None, error=None):
        self.frame = frame if frame is not None else blank_frame()
        self.error = error
        self.calls = []

    def render(self, profile, size):
        self.calls.append((profile, size))
        if self.error is not None:
            raise self.error
        return self.frame


class FlakyDisplay(FakeDisplay):
    """Display double raising a hardware-style error only when armed."""

    def __init__(self, error):
        super().__init__()
        self.error = error
        self.armed = False

    def show(self, frame):
        if self.armed:
            raise self.error
        super().show(frame)


class _ConcurrencyGate:
    """Counts concurrent entries into a critical section, blocking the first."""

    def __init__(self, started, release):
        self._started = started
        self._release = release
        self.active = 0
        self.max_concurrent = 0

    def __enter__(self):
        self.active += 1
        self.max_concurrent = max(self.max_concurrent, self.active)
        self._started.set()
        self._release.wait(timeout=5)

    def __exit__(self, *exc_info):
        self.active -= 1


class BlockingStore:
    """ProfileStore wrapper that blocks inside load() until released."""

    def __init__(self, store, started, release):
        self._store = store
        self._gate = _ConcurrencyGate(started, release)

    @property
    def max_concurrent(self):
        return self._gate.max_concurrent

    def load(self, name):
        with self._gate:
            return self._store.load(name)


class BlockingRenderer(StubRenderer):
    """Renderer double that blocks inside render() until released."""

    def __init__(self, started, release):
        super().__init__()
        self._gate = _ConcurrencyGate(started, release)

    @property
    def max_concurrent(self):
        return self._gate.max_concurrent

    def render(self, profile, size):
        with self._gate:
            return super().render(profile, size)


class BlockingDisplay(FakeDisplay):
    """Display double that blocks inside show() until released."""

    def __init__(self, started, release):
        super().__init__()
        self._gate = _ConcurrencyGate(started, release)

    @property
    def max_concurrent(self):
        return self._gate.max_concurrent

    def show(self, frame):
        with self._gate:
            super().show(frame)


@pytest.fixture
def store(tmp_path):
    (tmp_path / "first.csv").write_text(csv_text([("kb_w", "up")], title="First"))
    (tmp_path / "second.csv").write_text(
        csv_text([("kb_s", "down"), ("kb_a", "left")], title="Second")
    )
    (tmp_path / "broken.csv").write_text("this is not a quadstick export\n")
    return ProfileStore(tmp_path)


@pytest.fixture
def renderer():
    return StubRenderer()


@pytest.fixture
def device():
    return FakeDisplay()


@pytest.fixture
def controller(store, renderer, device):
    return DisplayController(store=store, renderer=renderer, device=device)


def run_concurrent_shows(controller, started, release):
    """Drive two show_profile calls; the first blocks mid-transaction.

    The blocking double sets ``started`` once inside the transaction; the
    second thread is then given every chance to interleave before the first
    is released. Returns ``(results, errors)`` keyed by profile name.
    """
    results, errors = {}, {}

    def worker(name):
        try:
            results[name] = controller.show_profile(name)
        # Broad catch is intentional: record any worker failure so the
        # caller can assert on it (was: pragma comment "asserted by the caller").
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            errors[name] = exc

    first = threading.Thread(target=worker, args=("first.csv",))
    second = threading.Thread(target=worker, args=("second.csv",))
    first.start()
    assert started.wait(timeout=5), "blocking double never entered the transaction"
    second.start()
    time.sleep(0.2)
    release.set()
    for thread in (first, second):
        thread.join(timeout=5)
        assert not thread.is_alive()
    return results, errors


class TestInitialStatus:
    def test_status_starts_empty(self, controller):
        assert controller.status == DisplayStatus(current_profile=None, last_error=None)

    def test_status_is_an_immutable_snapshot(self, controller):
        with pytest.raises(dataclasses.FrozenInstanceError):
            controller.status.current_profile = "first.csv"


class TestSuccessfulShow:
    def test_show_returns_and_publishes_the_success_status(self, controller):
        returned = controller.show_profile("first.csv")
        assert returned == DisplayStatus(current_profile="first.csv", last_error=None)
        assert controller.status == returned

    def test_show_loads_renders_and_shows_one_frame(self, controller, renderer, device):
        controller.show_profile("first.csv")
        (call,) = renderer.calls
        profile, size = call
        assert profile == Profile(name="First", bindings=(Binding("kb_w", "up"),))
        assert size == PRODUCTION_SIZE
        assert device.frames == [renderer.frame]

    def test_the_renderers_own_frame_object_reaches_the_device(
        self, controller, renderer, device
    ):
        controller.show_profile("first.csv")
        assert device.frames[0] is renderer.frame

    def test_successive_shows_replace_the_current_profile(self, controller, device):
        controller.show_profile("first.csv")
        controller.show_profile("second.csv")
        assert controller.status == DisplayStatus(
            current_profile="second.csv", last_error=None
        )
        assert len(device.frames) == 2


class TestModelFailures:
    def test_missing_profile_raises_the_typed_error(self, controller):
        with pytest.raises(ProfileNotFound) as excinfo:
            controller.show_profile("missing.csv")
        assert controller.status.current_profile is None
        assert controller.status.last_error == str(excinfo.value)

    def test_missing_profile_never_renders_or_shows(self, controller, renderer, device):
        with pytest.raises(ProfileNotFound):
            controller.show_profile("missing.csv")
        assert renderer.calls == []
        assert device.frames == []

    def test_invalid_content_raises_the_typed_error(self, controller):
        with pytest.raises(InvalidProfile) as excinfo:
            controller.show_profile("broken.csv")
        assert controller.status.current_profile is None
        assert controller.status.last_error == str(excinfo.value)

    @pytest.mark.parametrize("name", ["", "noextension", "../evil.csv", "a/b.csv"])
    def test_unsafe_names_raise_the_typed_error(
        self, controller, renderer, device, name
    ):
        with pytest.raises(InvalidProfileName) as excinfo:
            controller.show_profile(name)
        assert controller.status.current_profile is None
        assert controller.status.last_error == str(excinfo.value)
        assert renderer.calls == []
        assert device.frames == []

    def test_failure_preserves_the_previous_profile(self, controller, device):
        controller.show_profile("first.csv")
        with pytest.raises(ProfileNotFound) as excinfo:
            controller.show_profile("missing.csv")
        assert controller.status == DisplayStatus(
            current_profile="first.csv", last_error=str(excinfo.value)
        )
        assert len(device.frames) == 1


class TestRendererAndDisplayFailures:
    def test_renderer_error_is_wrapped_as_display_failure_with_chaining(
        self, store, device
    ):
        cause = ValueError("bad glyphs")
        controller = DisplayController(
            store=store, renderer=StubRenderer(error=cause), device=device
        )
        with pytest.raises(DisplayFailure) as excinfo:
            controller.show_profile("first.csv")
        assert excinfo.value.__cause__ is cause
        assert "first.csv" in str(excinfo.value)
        assert "bad glyphs" in str(excinfo.value)
        assert controller.status == DisplayStatus(
            current_profile=None, last_error=str(excinfo.value)
        )
        assert device.frames == []

    def test_display_error_is_wrapped_as_display_failure_with_chaining(
        self, store, renderer
    ):
        cause = OSError("panel offline")
        device = FlakyDisplay(cause)
        device.armed = True
        controller = DisplayController(store=store, renderer=renderer, device=device)
        with pytest.raises(DisplayFailure) as excinfo:
            controller.show_profile("first.csv")
        assert excinfo.value.__cause__ is cause
        assert "panel offline" in str(excinfo.value)
        assert controller.status == DisplayStatus(
            current_profile=None, last_error=str(excinfo.value)
        )
        assert device.frames == []

    def test_display_failure_preserves_the_previous_profile(self, store, renderer):
        device = FlakyDisplay(OSError("panel offline"))
        controller = DisplayController(store=store, renderer=renderer, device=device)
        controller.show_profile("first.csv")
        device.armed = True
        with pytest.raises(DisplayFailure):
            controller.show_profile("second.csv")
        assert controller.status.current_profile == "first.csv"
        assert "panel offline" in controller.status.last_error
        assert len(device.frames) == 1

    def test_success_after_a_failure_clears_the_error(self, store, renderer):
        device = FlakyDisplay(OSError("panel offline"))
        device.armed = True
        controller = DisplayController(store=store, renderer=renderer, device=device)
        with pytest.raises(DisplayFailure):
            controller.show_profile("first.csv")
        device.armed = False
        status = controller.show_profile("first.csv")
        assert status == DisplayStatus(current_profile="first.csv", last_error=None)
        assert len(device.frames) == 1


class TestSerialization:
    def test_load_is_inside_the_transaction_lock(self, store, renderer, device):
        started, release = threading.Event(), threading.Event()
        blocking = BlockingStore(store, started, release)
        controller = DisplayController(store=blocking, renderer=renderer, device=device)
        results, errors = run_concurrent_shows(controller, started, release)
        assert errors == {}
        assert set(results) == {"first.csv", "second.csv"}
        assert blocking.max_concurrent == 1
        assert len(device.frames) == 2

    def test_render_is_inside_the_transaction_lock(self, store, device):
        started, release = threading.Event(), threading.Event()
        renderer = BlockingRenderer(started, release)
        controller = DisplayController(store=store, renderer=renderer, device=device)
        results, errors = run_concurrent_shows(controller, started, release)
        assert errors == {}
        assert set(results) == {"first.csv", "second.csv"}
        assert renderer.max_concurrent == 1
        assert len(device.frames) == 2

    def test_show_is_inside_the_transaction_lock(self, store, renderer):
        started, release = threading.Event(), threading.Event()
        device = BlockingDisplay(started, release)
        controller = DisplayController(store=store, renderer=renderer, device=device)
        results, errors = run_concurrent_shows(controller, started, release)
        assert errors == {}
        assert set(results) == {"first.csv", "second.csv"}
        assert device.max_concurrent == 1
        assert len(device.frames) == 2
        assert all(status.last_error is None for status in results.values())
        assert controller.status.current_profile in {"first.csv", "second.csv"}


class TestRealRendererIntegration:
    def test_real_renderer_produces_a_panel_ready_frame(self, tmp_path):
        (tmp_path / "game.csv").write_text(
            csv_text([("kb_w", "up"), ("kb_space", "mp_center_sip")], title="Game")
        )
        device = FakeDisplay()
        controller = DisplayController(
            store=ProfileStore(tmp_path),
            renderer=ProfileRenderer(RESOURCES),
            device=device,
        )
        status = controller.show_profile("game.csv")
        assert status == DisplayStatus(current_profile="game.csv", last_error=None)
        (frame,) = device.frames
        for plane in (frame.black, frame.red):
            assert plane.mode == "1"
            assert plane.size == (400, 300)
