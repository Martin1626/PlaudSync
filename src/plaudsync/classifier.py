"""Classifier hook for sync engine.

Default v0 implementation returns '_unclassified' for every recording.
Real classifier (categorization layer) implements the same Protocol.
"""
from __future__ import annotations

from typing import Any, Protocol


class Classifier(Protocol):
    def classify(self, recording: Any) -> str: ...


class DefaultBucketClassifier:
    def classify(self, recording: Any) -> str:
        return "_unclassified"
