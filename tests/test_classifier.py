"""Unit tests for src/plaudsync/classifier.py."""
from __future__ import annotations

from plaudsync.classifier import Classifier, DefaultBucketClassifier


def test_default_bucket_classifier_returns_unclassified() -> None:
    clf = DefaultBucketClassifier()
    # Use plain dict — Protocol structural typing accepts any object with .title etc.
    class _Meta:
        title = "anything"
        plaud_id = "x"
    assert clf.classify(_Meta()) == "_unclassified"


def test_default_bucket_classifier_satisfies_protocol() -> None:
    clf: Classifier = DefaultBucketClassifier()  # Protocol check via type annotation
    assert hasattr(clf, "classify")
