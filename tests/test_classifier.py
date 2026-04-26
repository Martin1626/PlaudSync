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


def test_categorization_classifier_returns_project_for_matched_title() -> None:
    from plaudsync.classifier import CategorizationClassifier

    class _Meta:
        title = "04-26 Alza: test1"
        created_at = "2026-04-26T14:31:14.631000+00:00"
        plaud_id = "abc"

    clf = CategorizationClassifier()
    assert clf.classify(_Meta()) == "Alza"


def test_categorization_classifier_returns_unclassified_for_no_match() -> None:
    from plaudsync.classifier import CategorizationClassifier

    class _Meta:
        title = "random text without project pattern"
        created_at = "2026-04-26T14:31:14.631000+00:00"
        plaud_id = "abc"

    clf = CategorizationClassifier()
    assert clf.classify(_Meta()) == "_unclassified"


def test_categorization_classifier_satisfies_protocol() -> None:
    from plaudsync.classifier import CategorizationClassifier, Classifier

    clf: Classifier = CategorizationClassifier()
    assert hasattr(clf, "classify")


def test_categorization_classifier_handles_z_suffix_iso_timestamp() -> None:
    """Plaud API may return UTC timestamps with 'Z' suffix instead of +00:00."""
    from plaudsync.classifier import CategorizationClassifier

    class _Meta:
        title = "04-26 FHB: test"
        created_at = "2026-04-26T14:31:14Z"
        plaud_id = "abc"

    clf = CategorizationClassifier()
    assert clf.classify(_Meta()) == "FHB"
