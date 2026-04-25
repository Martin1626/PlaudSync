"""VCR cassette tests for PlaudClient region probe."""
from __future__ import annotations

import pytest

from plaudsync.plaud_client import PlaudClient, PlaudRegionProbeFailed


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_region")
def test_region_redirect_eu() -> None:
    with PlaudClient("test-token") as client:
        assert client._base_url == "https://api-euc1.plaud.ai"


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_region")
def test_region_default_us() -> None:
    with PlaudClient("test-token") as client:
        assert client._base_url == "https://api.plaud.ai"


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_region")
def test_region_unexpected_shape() -> None:
    with pytest.raises(PlaudRegionProbeFailed):
        PlaudClient("test-token")


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_region")
def test_region_redirect_non_plaud_host() -> None:
    # SSRF guard: redirect target must be a plaud.ai subdomain.
    with pytest.raises(PlaudRegionProbeFailed):
        PlaudClient("test-token")


@pytest.mark.vcr(cassette_library_dir="tests/cassettes/test_plaud_client_region")
def test_region_redirect_http_scheme() -> None:
    # SSRF guard: redirect target must use https.
    with pytest.raises(PlaudRegionProbeFailed):
        PlaudClient("test-token")
