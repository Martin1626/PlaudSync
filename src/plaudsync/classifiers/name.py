"""Strategy 1 — regex match on recording title.

Wraps existing ``plaudsync.categorization.classify`` into the
``Classifier`` protocol shape (recording → str label). Returns
``"_unclassified"`` on no-match or invalid created_at.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from plaudsync.categorization import classify as _categorization_classify


class NameClassifier:
    def classify(self, recording: Any) -> str:
        title = getattr(recording, "title", "")
        created_raw = getattr(recording, "created_at", "")
        try:
            created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return "_unclassified"
        result = _categorization_classify(title, created_at)
        if result.status == "matched":
            assert result.project is not None
            return result.project
        return "_unclassified"
