"""Unit tests for the pure domain model (quadstick_display.model).

Pins the M1 semantic model: raw (command, quadstick input) pairs parsed with
``csv.reader`` — title from the last non-empty value of the first row,
mappings after the ``Output or Function`` header, command column 0, input
column 2, stop before ``Preferences``, duplicates and row order preserved —
plus the strict single-file-name policy of ``ProfileStore``.
"""

import dataclasses
import io
import subprocess
import sys
from pathlib import Path

import pytest

from quadstick_display.model import (
    Binding,
    InvalidProfile,
    InvalidProfileName,
    ProfileNotFound,
    ProfileStore,
    parse_quadstick_csv,
)

CSVS_DIR = Path(__file__).resolve().parents[2] / "resources" / "quadstick_csvs"
AD_INFINITUM = CSVS_DIR / "ad_infinitum.csv"
ALAN_WAKE_II = CSVS_DIR / "alan_wake_II.csv"

# Raw (column 0, column 2) pairs in file order; cleanup/uppercasing is a
# presentation concern and must NOT happen in the model.
AD_INFINITUM_BINDINGS = [
    ("kb_w", "up"),
    ("kb_s", "down"),
    ("kb_a", "left"),
    ("kb_d", "right"),
    ("kb_q", "right_puff"),
    ("kb_r", "mp_center_sip"),
    ("mouse_right_button", "mp_center_puff"),
    ("kb_space", "mp_center_sip_soft"),
    ("kb_enter", "lip"),
    ("kb_left_shift", "mp_left_center_sip"),
    ("kb_left_control", "mp_left_center_puff"),
    ("kb_tab", "mp_right_center_sip"),
    ("kb_g", "mp_right_center_puff"),
    ("kb_right_arrow", "mp_right_sip"),
    ("kb_left_arrow", "mp_left_sip"),
    ("kb_escape", "right_sip"),
]

ALAN_WAKE_II_BINDINGS = [
    ("kb_w", "up"),
    ("kb_s", "down"),
    ("kb_a", "left"),
    ("kb_d", "right"),
    ("kb_space", "mp_center_sip"),
    ("mouse_right_button", "mp_center_puff"),
    ("kb_r", "mp_left_sip"),
    ("kb_left_shift", "mp_left_center_puff"),
    ("kb_f", "lip"),
    ("kb_e", "mp_left_center_sip"),
    ("mouse_middle_button", "mp_left_puff"),
    ("kb_q", "mp_left_sip_soft"),
    ("mouse_wheel_up", "right_sip_soft"),
    ("mouse_wheel_down", "right_puff_soft"),
    ("kb_left_control", "mp_right_center_sip"),
    ("kb_tab", "mp_right_center_puff"),
    ("kb_m", "right_puff"),
    ("kb_escape", "right_sip"),
    ("kb_1", "mp_left_center_sip_soft"),
    ("kb_2", "mp_left_center_puff_soft"),
    ("kb_3", "mp_right_center_sip_soft"),
    ("kb_4", "mp_right_center_puff_soft"),
    ("kb_left_alt", "mp_right_sip"),
    ("kb_z", "mp_right_sip"),
]


def as_text(pairs, header="Output or Function,Function,usb", first_row=None):
    first_row = first_row or "QuadStick Configuration,Version 1.5,HASH,Some Game"
    rows = [first_row, "Profile Name,,Inputs", "some.csv,,Normal", header]
    rows += [f"{command},normal,{qs_input}" for command, qs_input in pairs]
    return "\n".join(rows) + "\n"


class TestFixtureParity:
    def test_ad_infinitum_name_and_binding_count(self):
        with AD_INFINITUM.open(newline="", encoding="utf-8") as stream:
            profile = parse_quadstick_csv(stream)
        assert profile.name == "Ad_Infinitum"
        assert len(profile.bindings) == 16

    def test_alan_wake_ii_name_and_binding_count(self):
        with ALAN_WAKE_II.open(newline="", encoding="utf-8") as stream:
            profile = parse_quadstick_csv(stream)
        assert profile.name == "Alan Wake II"
        assert len(profile.bindings) == 24

    def test_ad_infinitum_rows_in_order(self):
        with AD_INFINITUM.open(newline="", encoding="utf-8") as stream:
            profile = parse_quadstick_csv(stream)
        assert [(b.command, b.quadstick_input) for b in profile.bindings] == (
            AD_INFINITUM_BINDINGS
        )

    def test_alan_wake_ii_rows_in_order(self):
        with ALAN_WAKE_II.open(newline="", encoding="utf-8") as stream:
            profile = parse_quadstick_csv(stream)
        assert [(b.command, b.quadstick_input) for b in profile.bindings] == (
            ALAN_WAKE_II_BINDINGS
        )

    def test_duplicate_bindings_are_preserved_in_order(self):
        with ALAN_WAKE_II.open(newline="", encoding="utf-8") as stream:
            profile = parse_quadstick_csv(stream)
        pairs = [(b.command, b.quadstick_input) for b in profile.bindings]
        assert pairs[-2:] == [
            ("kb_left_alt", "mp_right_sip"),
            ("kb_z", "mp_right_sip"),
        ]
        assert [p for p in pairs if p[1] == "mp_right_sip"] == [
            ("kb_left_alt", "mp_right_sip"),
            ("kb_z", "mp_right_sip"),
        ]

    def test_bindings_are_tuples_of_frozen_dataclasses(self):
        with AD_INFINITUM.open(newline="", encoding="utf-8") as stream:
            profile = parse_quadstick_csv(stream)
        assert isinstance(profile.bindings, tuple)
        assert all(isinstance(b, Binding) for b in profile.bindings)
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.bindings[0].command = "kb_x"


class TestParserSemantics:
    def test_title_is_last_non_empty_value_of_first_row(self):
        text = as_text(
            [("kb_a", "up")],
            first_row="QuadStick Configuration,Version 1.5, Trailing Name ,,,",
        )
        assert parse_quadstick_csv(io.StringIO(text)).name == "Trailing Name"

    def test_stops_before_preferences_section(self):
        text = as_text([("kb_a", "up")]) + (
            "\nPreferences,,,,\n"
            ",,,,\n"
            "Preference,Value,Units,Description,\n"
            "digital_out_1,0,on/off,Initial output state for relay 1,\n"
        )
        profile = parse_quadstick_csv(io.StringIO(text))
        assert [(b.command, b.quadstick_input) for b in profile.bindings] == [
            ("kb_a", "up"),
        ]

    def test_skips_rows_with_empty_command_or_input(self):
        text = as_text([("kb_a", "up")]).replace(
            "kb_a,normal,up", "kb_a,normal,up\n,normal,down\nkb_b,normal,"
        )
        profile = parse_quadstick_csv(io.StringIO(text))
        assert [(b.command, b.quadstick_input) for b in profile.bindings] == [
            ("kb_a", "up"),
        ]

    def test_blank_lines_inside_mapping_section_are_skipped(self):
        text = as_text([("kb_a", "up"), ("kb_b", "down")]).replace(
            "kb_a,normal,up", "kb_a,normal,up\n"
        )
        profile = parse_quadstick_csv(io.StringIO(text))
        assert [(b.command, b.quadstick_input) for b in profile.bindings] == [
            ("kb_a", "up"),
            ("kb_b", "down"),
        ]


class TestMalformedProfiles:
    def test_empty_stream_is_invalid(self):
        with pytest.raises(InvalidProfile):
            parse_quadstick_csv(io.StringIO(""))

    def test_first_row_without_any_value_is_invalid(self):
        with pytest.raises(InvalidProfile):
            parse_quadstick_csv(io.StringIO(",,,\nOutput or Function,f,u\n"))

    def test_missing_mapping_section_is_invalid(self):
        text = (
            "QuadStick Configuration,Version 1.5,HASH,Name\n"
            "Profile Name,,Inputs\n"
            "kb_w,normal,up\n"
        )
        with pytest.raises(InvalidProfile):
            parse_quadstick_csv(io.StringIO(text))

    def test_wrong_mapping_header_is_invalid(self):
        text = as_text([("kb_a", "up")], header="Outputs,Function,usb")
        with pytest.raises(InvalidProfile):
            parse_quadstick_csv(io.StringIO(text))


@pytest.fixture
def store(tmp_path):
    return ProfileStore(tmp_path)


class TestProfileStoreListing:
    def test_list_names_is_sorted_and_csv_only(self, tmp_path):
        for name in ["b.csv", "a.csv", "C.CSV", "notes.txt", "no_suffix"]:
            (tmp_path / name).write_text("x")
        store = ProfileStore(tmp_path)
        assert store.list_names() == ("a.csv", "b.csv")

    def test_list_names_empty_directory(self, store):
        assert store.list_names() == ()


class TestProfileStoreLoad:
    def test_load_parses_stored_profile(self, tmp_path):
        (tmp_path / "game.csv").write_text(as_text([("kb_a", "up")]))
        store = ProfileStore(tmp_path)
        profile = store.load("game.csv")
        assert profile.name == "Some Game"
        assert [(b.command, b.quadstick_input) for b in profile.bindings] == [
            ("kb_a", "up"),
        ]

    def test_load_fixture_profile(self, tmp_path):
        (tmp_path / "alan_wake_II.csv").write_bytes(ALAN_WAKE_II.read_bytes())
        store = ProfileStore(tmp_path)
        profile = store.load("alan_wake_II.csv")
        assert profile.name == "Alan Wake II"
        assert len(profile.bindings) == 24

    def test_missing_profile_raises_not_found(self, store):
        with pytest.raises(ProfileNotFound):
            store.load("missing.csv")

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "..",
            "../evil.csv",
            "a/../b.csv",
            "sub/dir.csv",
            "back\\slash.csv",
            "/abs/path.csv",
            "upper.CSV",
            "notes.txt",
            "no_suffix",
            ".csv",
        ],
    )
    def test_unsafe_or_non_csv_names_rejected(self, store, name):
        with pytest.raises(InvalidProfileName):
            store.load(name)

    def test_load_does_not_touch_files_outside_the_store(self, store, tmp_path):
        secret = tmp_path.parent / "secret.csv"
        secret.write_text(as_text([("kb_a", "up")]))
        with pytest.raises(InvalidProfileName):
            store.load("../secret.csv")
        with pytest.raises((InvalidProfileName, ProfileNotFound)):
            store.load(str(secret))


class TestProfileStoreSaveUpload:
    def test_saves_sanitized_name_and_returns_it(self, store, tmp_path):
        saved = store.save_upload("../../evil.csv", io.BytesIO(b"data"))
        assert saved == "evil.csv"
        assert (tmp_path / "evil.csv").read_bytes() == b"data"

    def test_round_trip_save_then_load(self, store):
        payload = as_text([("kb_a", "up"), ("kb_b", "down")]).encode()
        saved = store.save_upload("My Game.csv", io.BytesIO(payload))
        profile = store.load(saved)
        assert [(b.command, b.quadstick_input) for b in profile.bindings] == [
            ("kb_a", "up"),
            ("kb_b", "down"),
        ]

    def test_save_upload_overwrites_an_existing_same_name_file(self, store, tmp_path):
        first = store.save_upload("game.csv", io.BytesIO(b"first"))
        second = store.save_upload("game.csv", io.BytesIO(b"second"))
        assert first == second == "game.csv"
        assert (tmp_path / "game.csv").read_bytes() == b"second"

    def test_path_separators_are_sanitized_not_traversed(self, store, tmp_path):
        saved = store.save_upload("sub/dir.csv", io.BytesIO(b"data"))
        assert saved == "sub_dir.csv"
        assert (tmp_path / "sub_dir.csv").read_bytes() == b"data"
        assert not (tmp_path / "sub").exists()

    @pytest.mark.parametrize(
        "filename",
        ["", "..", "notes.txt", "game.CSV", "\U0001f4be.csv"],
    )
    def test_rejects_unsafe_or_non_csv_uploads(self, store, tmp_path, filename):
        with pytest.raises(InvalidProfileName):
            store.save_upload(filename, io.BytesIO(b"data"))
        assert list(tmp_path.iterdir()) == []

    def test_sanitization_matches_werkzeug_secure_filename(self):
        # Test-only parity check: the model must not import werkzeug, so it
        # replicates secure_filename semantics; pin that replication here.
        from werkzeug.utils import secure_filename

        from quadstick_display.model import _secure_filename

        for raw in [
            "../../evil.csv",
            "My Game.csv",
            "a/b\\c.csv",
            "  spaces  .csv",
            "ünïcodé.csv",
            "...csv",
            "name\r\nwith\twhitespace.csv",
            "trailing.CSV",
        ]:
            assert _secure_filename(raw) == secure_filename(raw)


class TestModelPurity:
    def test_model_imports_no_flask_pillow_pandas_or_hardware(self):
        code = (
            "import sys;"
            "import quadstick_display.model;"
            'banned = [m for m in sys.modules if m.split(".")[0] in'
            ' {"flask", "PIL", "pandas", "waveshare_epd", "spidev",'
            '  "gpiozero", "RPi", "lgpio", "Jetson"}];'
            "assert not banned, banned"
        )
        subprocess.run([sys.executable, "-c", code], check=True)
