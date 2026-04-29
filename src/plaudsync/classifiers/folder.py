"""Strategy 2 — Plaud folder ID → project lookup.

Pure config lookup via ``Config.lookup_by_folder_id``. Returns
``"_unclassified"`` when the recording is in no folder (``plaud_folder='_unknown'``)
or the folder ID is not mapped in config.
"""
from __future__ import annotations

from typing import Any

from plaudsync.config import Config


class FolderClassifier:
    def __init__(self, config: Config) -> None:
        self._config = config

    def classify(self, recording: Any) -> str:
        folder_id = getattr(recording, "plaud_folder", None)
        if not folder_id or folder_id == "_unknown":
            return "_unclassified"
        project = self._config.lookup_by_folder_id(folder_id)
        return project or "_unclassified"
