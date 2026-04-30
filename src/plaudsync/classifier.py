"""Classifier orchestration for sync engine.

WaterfallClassifier evaluates 3 strategies in order:
1. NameClassifier — regex match on title (with optional folder confirmation)
2. FolderClassifier — Plaud folder ID → project lookup
3. catch-all — _unclassified bucket (only when sync_unclassified=true)

Returns ClassificationOutcome(label, source). source='skip' signals to
sync.py that the recording should not be recorded in DB at all (replaces
the pre-BL-X sync_only_foldered semantic).

Back-compat shims (CategorizationClassifier, DefaultBucketClassifier)
preserved for existing call sites until full sync.py rewiring (Task 14).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from plaudsync.classifiers.folder import FolderClassifier
from plaudsync.classifiers.name import NameClassifier
from plaudsync.config import Config


class Classifier(Protocol):
    def classify(self, recording: Any) -> Any: ...


@dataclass(frozen=True)
class ClassificationOutcome:
    """Outcome of WaterfallClassifier.classify().

    label is None when source='skip' — sync engine reads this as 'do not
    record this recording in DB at all' (no metadata trace).
    """

    label: str | None
    source: Literal["name", "folder", "none", "skip"]


class WaterfallClassifier:
    """3-strategy waterfall: name → folder → catch-all (or skip)."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._name = NameClassifier()
        self._folder = FolderClassifier(config)

    def classify(self, recording: Any) -> ClassificationOutcome:
        meta_folder = getattr(recording, "plaud_folder", "_unknown")

        # Strategy 1 — name regex
        if self._config.classify_by_name:
            name_label = self._name.classify(recording)
            if name_label != "_unclassified":
                require_folder_blocks = (
                    self._config.classify_by_name_require_folder
                    and meta_folder == "_unknown"
                )
                in_config = self._config.lookup_project(name_label) is not None
                # Hotfix I (2026-04-30): fall through to folder strategy
                # when name match produces a project not in config. Common
                # case: title contains random project code (e.g. "CPR")
                # but recording is filed in a known Plaud folder (e.g.
                # "Školení"). Folder fallback wins; if folder also can't
                # classify, drop back to BL-3 skip path (return name label
                # with source='name' so sync.py records the row as
                # skipped_unknown_project for later retry once the user
                # adds the project to config).
                if not require_folder_blocks and in_config:
                    return ClassificationOutcome(label=name_label, source="name")
                if not require_folder_blocks and not in_config:
                    if self._config.classify_by_folder:
                        folder_label = self._folder.classify(recording)
                        if folder_label != "_unclassified":
                            return ClassificationOutcome(
                                label=folder_label, source="folder",
                            )
                    # No folder fallback worked — preserve BL-3 retry path
                    # by returning the unknown name label with source='name'.
                    return ClassificationOutcome(label=name_label, source="name")
                # require_folder_blocks → fall through to folder/catch-all

        # Strategy 2 — Plaud folder lookup
        if self._config.classify_by_folder:
            label = self._folder.classify(recording)
            if label != "_unclassified":
                return ClassificationOutcome(label=label, source="folder")

        # Strategy 3 — catch-all to unclassified bucket
        if self._config.sync_unclassified:
            return ClassificationOutcome(label="_unclassified", source="none")

        # No strategy matched + no catch-all → outright skip (no DB row)
        return ClassificationOutcome(label=None, source="skip")


# ---------------------------------------------------------------------------
# Back-compat shims for tests / call sites still on the str-returning protocol.
# Removed in Task 14 once sync.py + __main__.py migrate to WaterfallClassifier.
# ---------------------------------------------------------------------------

class CategorizationClassifier:
    """DEPRECATED — use WaterfallClassifier. Wraps NameClassifier in str protocol."""

    def __init__(self) -> None:
        self._inner = NameClassifier()

    def classify(self, recording: Any) -> str:
        return self._inner.classify(recording)


class DefaultBucketClassifier:
    """DEPRECATED placeholder — returns '_unclassified' for any recording."""

    def classify(self, recording: Any) -> str:
        return "_unclassified"
