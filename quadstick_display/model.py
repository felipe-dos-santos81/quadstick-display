"""Pure domain model for Quadstick profiles.

This module is deliberately free of Flask, Pillow, pandas, and hardware
imports: it parses Quadstick spreadsheet CSV exports into an immutable
semantic model and stores/loads them from a directory with a strict
single-file-name policy.

CSV layout produced by the Quadstick spreadsheet export::

    QuadStick Configuration,Version 1.5,<hash>,<profile title>
    Profile Name,,Inputs,...
    <file name>,,Normal,...
    Output or Function,Function,usb,...
    <command>,<mode>,<quadstick input>,...
    ... (more mapping rows, duplicates allowed, order matters)
    <blank line>
    Preferences,,,,
    ... (preference rows, not part of the mapping model)

The title is the last non-empty value of the first row. Mapping rows follow
the ``Output or Function`` header: command is column 0, quadstick input is
column 2, and the section ends at the ``Preferences`` row. Rows with an
empty command or input are skipped.
"""
import csv
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO, TextIO

MAPPING_HEADER = 'Output or Function'
PREFERENCES_MARKER = 'preferences'
CSV_SUFFIX = '.csv'


class InvalidProfile(ValueError):
    """The CSV content does not describe a valid Quadstick profile."""


class InvalidProfileName(ValueError):
    """A profile file name violates the single-file-name safety policy."""


class ProfileNotFound(FileNotFoundError):
    """No profile with the requested (valid) name exists in the store."""


@dataclass(frozen=True)
class Binding:
    """One raw mapping row: a command bound to a Quadstick input."""

    command: str
    quadstick_input: str


@dataclass(frozen=True)
class Profile:
    """A parsed Quadstick profile: title plus ordered bindings."""

    name: str
    bindings: tuple[Binding, ...]


def parse_quadstick_csv(stream: TextIO) -> Profile:
    """Parse a Quadstick CSV export from a text stream into a ``Profile``.

    Raises ``InvalidProfile`` when the first row has no usable title or when
    the ``Output or Function`` mapping section is missing.
    """
    rows = csv.reader(stream)

    first_row = next(rows, None)
    title = _last_non_empty(first_row) if first_row else None
    if title is None:
        raise InvalidProfile('first row has no profile title')

    for row in rows:
        if row and row[0].strip() == MAPPING_HEADER:
            break
    else:
        raise InvalidProfile(f'missing {MAPPING_HEADER!r} mapping section')

    bindings = []
    for row in rows:
        if not row:
            continue
        command = row[0].strip()
        if command.casefold() == PREFERENCES_MARKER:
            break
        if len(row) < 3:
            continue
        quadstick_input = row[2].strip()
        if not command or not quadstick_input:
            continue
        bindings.append(Binding(command, quadstick_input))

    return Profile(name=title, bindings=tuple(bindings))


def _last_non_empty(row):
    for cell in reversed(row):
        value = cell.strip()
        if value:
            return value
    return None


class ProfileStore:
    """Directory-backed store of Quadstick profile CSV files.

    All names accepted by ``load``/``save_upload`` (and therefore all names
    returned by ``list_names``) follow a strict single-file-name policy:
    no absolute paths, no empty names, no ``..``, no path separators, and a
    lowercase ``.csv`` suffix. Upload file names are first sanitized with
    werkzeug's ``secure_filename`` semantics.
    """

    def __init__(self, directory):
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def list_names(self) -> tuple[str, ...]:
        """Return the sorted names of the stored ``.csv`` profiles."""
        return tuple(
            sorted(
                entry.name
                for entry in self._directory.iterdir()
                if entry.is_file() and _has_csv_suffix(entry.name)
            )
        )

    def load(self, name: str) -> Profile:
        """Parse and return the stored profile ``name``.

        Raises ``InvalidProfileName`` for unsafe names, ``ProfileNotFound``
        when no such file exists, and ``InvalidProfile`` for bad content.
        """
        _validate_name(name)
        path = self._directory / name
        if not path.is_file():
            raise ProfileNotFound(name)
        try:
            with path.open(newline='', encoding='utf-8') as stream:
                return parse_quadstick_csv(stream)
        except UnicodeDecodeError as exc:
            raise InvalidProfile(f'{name!r} is not valid UTF-8 text') from exc

    def save_upload(self, filename: str, stream: BinaryIO) -> str:
        """Store an uploaded CSV under its sanitized name; return that name.

        Raises ``InvalidProfileName`` when the sanitized name is not a safe
        single ``.csv`` file name.
        """
        safe_name = _secure_filename(filename)
        _validate_name(safe_name)
        with (self._directory / safe_name).open('wb') as target:
            shutil.copyfileobj(stream, target)
        return safe_name


def _has_csv_suffix(name: str) -> bool:
    return PurePath(name).suffix == CSV_SUFFIX


def _validate_name(name: str) -> None:
    """Enforce the strict single-file-name policy on stored profiles."""
    if (
        not name
        or '..' in name
        or '/' in name
        or '\\' in name
        or PurePath(name).is_absolute()
        or not _has_csv_suffix(name)
    ):
        raise InvalidProfileName(
            f'unsafe profile name: {name!r} (expected a single lowercase '
            f'{CSV_SUFFIX!r} file name, no paths or traversal)'
        )


# --- werkzeug secure_filename semantics -------------------------------------
# Replicated from werkzeug.utils.secure_filename so the model stays free of
# web-framework imports; tests pin parity with werkzeug itself.
_FILENAME_ASCII_STRIP_RE = re.compile(r'[^A-Za-z0-9_.-]')
_WINDOWS_DEVICE_FILES = {
    'CON', 'AUX', 'NUL', 'PRN',
    *(f'{base}{n}' for base in ('COM', 'LPT') for n in range(1, 10)),
}


def _secure_filename(filename: str) -> str:
    """Return a safe version of ``filename`` (werkzeug semantics)."""
    import os

    filename = unicodedata.normalize('NFKD', filename)
    filename = filename.encode('ascii', 'ignore').decode()

    for sep in (os.sep, os.altsep):
        if sep:
            filename = filename.replace(sep, '_')
    filename = str(
        _FILENAME_ASCII_STRIP_RE.sub('', '_'.join(filename.split()))
    ).strip('._')

    if (
        os.name == 'nt'
        and filename
        and filename.split('.')[0].upper() in _WINDOWS_DEVICE_FILES
    ):
        filename = f'_{filename}'

    return filename
