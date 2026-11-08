"""Schema initialization entry point kept separate from repository access."""

from __future__ import annotations

from pathlib import Path
from typing import Union

from .repository import Repository


def initialize_database(path: Union[str, Path]) -> Repository:
    return Repository(path)


__all__ = ["initialize_database"]
