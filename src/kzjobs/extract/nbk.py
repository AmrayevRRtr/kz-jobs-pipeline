"""Extractor for official exchange rates of the National Bank of Kazakhstan (XML/RSS)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import defusedxml.ElementTree as ET
import httpx

from kzjobs.config import Settings


class NBKError(RuntimeError):
    pass


def fetch_rates_xml(settings: Settings, on: date, client: httpx.Client | None = None) -> str:
    """Download the rates table for a date. URL format: ...get_rates.cfm?fdate=DD.MM.YYYY"""
    owns = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        resp = client.get(settings.nbk_rates_url, params={"fdate": on.strftime("%d.%m.%Y")})
    finally:
        if owns:
            client.close()
    if resp.status_code != 200:
        raise NBKError(f"NBK returned {resp.status_code}")
    return resp.text


def parse_rates(
    xml_text: str | bytes, fallback_date: date | None = None
) -> tuple[date, dict[str, Decimal]]:
    """Parse the NBK XML into ``(rate_date, {currency: KZT per 1 unit})``."""
    data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NBKError(f"invalid XML: {exc}") from exc

    raw_date = (root.findtext("date") or "").strip()
    try:
        rate_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
    except ValueError:
        if fallback_date is None:
            raise NBKError(f"cannot read rate date: {raw_date!r}") from None
        rate_date = fallback_date

    rates: dict[str, Decimal] = {}
    for item in root.iter("item"):
        code = (item.findtext("title") or "").strip().upper()
        try:
            price = Decimal((item.findtext("description") or "").strip().replace(",", "."))
            quant = Decimal((item.findtext("quant") or "1").strip())
        except InvalidOperation:
            continue
        if code and price > 0 and quant > 0:
            rates[code] = price / quant
    if not rates:
        raise NBKError("no rates found in XML")
    return rate_date, rates
