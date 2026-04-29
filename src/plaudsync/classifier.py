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
            label = self._name.classify(recording)
            if label != "_unclassified":
                if self._config.classify_by_name_require_folder and meta_folder == "_unknown":
                    pass  # fall-through — defensive trust requires folder
                else:
                    return ClassificationOutcome(label=label, source="name")

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
