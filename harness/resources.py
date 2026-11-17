"""Locate bundled data: the project template, the Hermes plugin and the profile definitions.

An installed wheel carries them in `harness/_data/` (see pyproject.toml force-include). A git
checkout or editable install reads them from their source folders in the repo.
"""
from __future__ import annotations

from pathlib import Path

_PKG = Path(__file__).resolve().parent
_SOURCE = {"template": "template", "plugin": "hermes/plugin", "profiles": "profiles"}


def data_dir(name: str) -> Path:
    """Directory for `name` (template | plugin | profiles). May not exist; callers check."""
    if name not in _SOURCE:
        raise KeyError(name)
    bundled = _PKG / "_data" / name
    return bundled if bundled.is_dir() else _PKG.parent / _SOURCE[name]
