"""Classifier hook for sync engine.

Default v0 implementation returns '_unclassified' for every recording
(retained as a test fixture). Production sync wiring in __main__.py uses
CategorizationClassifier, which adapts plaudsync.categorization.classify
into the Classifier Protocol shape.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from plaudsync.categorization import classify as _categorization_classify


class Classifier(Protocol):
    def classify(self, recording: Any) -> str: ...


class DefaultBucketClassifier:
    def classify(self, recording: Any) -> str:
        return "_unclassified"


class CategorizationClassifier:
    """Adapter from categorization.classify(title, created_at) to
    Classifier Protocol (recording -> str label).
    """

    def classify(self, recording: Any) -> str:
        title = getattr(recording, "title")
        created_at_raw = getattr(recording, "created_at")
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        result = _categorization_classify(title, created_at)
        if result.status == "matched":
            assert result.project is not None
            return result.project
        return "_unclassified"
