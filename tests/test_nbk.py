from datetime import date
from decimal import Decimal

import pytest

from kzjobs.extract.nbk import NBKError, parse_rates


def test_parse_rates_normalises_quantity(fx_xml):
    rate_date, rates = parse_rates(fx_xml)
    assert rate_date == date(2026, 11, 17)
    assert rates["USD"] == Decimal("500.00")
    assert rates["JPY"] == Decimal("3.3")


def test_missing_date_uses_fallback():
    xml = "<rates><item><title>USD</title><description>500</description><quant>1</quant></item></rates>"
    rate_date, rates = parse_rates(xml, fallback_date=date(2026, 1, 2))
    assert rate_date == date(2026, 1, 2) and rates["USD"] == Decimal(500)


def test_broken_row_is_skipped_not_fatal():
    xml = (
        "<rates><date>01.02.2026</date>"
        "<item><title>USD</title><description>oops</description><quant>1</quant></item>"
        "<item><title>EUR</title><description>580</description><quant>1</quant></item></rates>"
    )
    _, rates = parse_rates(xml)
    assert set(rates) == {"EUR"}


def test_invalid_xml_raises():
    with pytest.raises(NBKError):
        parse_rates("<rates><unclosed>")


def test_entity_expansion_is_blocked():
    """defusedxml must refuse XML entity tricks (billion laughs / XXE)."""
    bomb = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><rates><date>01.02.2026</date>&a;</rates>'
    with pytest.raises(Exception):  # noqa: B017 - defusedxml raises EntitiesForbidden
        parse_rates(bomb)
