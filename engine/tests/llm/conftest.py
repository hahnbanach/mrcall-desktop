"""Isolate tests/llm from the Supabase-requiring autouse fixture in
tests/conftest.py — these unit tests need no storage at all.

`price_snapshot` is the one way a test here pins a price (milestone 10, slice
S3): the committed fixture snapshot (`price_fixture.py`) as the only layer
the price source reads, never the build copy the coordinator refreshes.
`billed_snapshot` is the same snapshot with the two OpenRouter rates 10a
billed that were not the catalogue's put back, for the tests written before
the snapshot: their prices stay, their OpenRouter ceilings gain the margin.
"""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override parent autouse fixture; no-op here."""
    yield


@pytest.fixture
def price_snapshot():
    """The committed fixture snapshot as the only catalogue layer for the
    test; the build copy is the layer again afterwards."""
    from zylch.llm.roles import catalogue

    from .price_fixture import fixture

    doc = fixture()
    catalogue.set_layers(doc, build=False)
    yield doc
    catalogue.set_layers()


@pytest.fixture
def billed_snapshot():
    """`price_snapshot` as 10a billed it (`price_fixture.as_billed_by_10a`)."""
    from zylch.llm.roles import catalogue

    from .price_fixture import as_billed_by_10a, fixture

    doc = as_billed_by_10a(fixture())
    catalogue.set_layers(doc, build=False)
    yield doc
    catalogue.set_layers()
