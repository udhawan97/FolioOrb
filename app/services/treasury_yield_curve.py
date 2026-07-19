"""
US Treasury par yield curve — the shape of the risk-free curve.

Keyless, public-domain feed (home.treasury.gov), republished every business day
around 16:00 ET. The curve's shape is the cleanest free read on what the bond
market expects: when 10-year yields sit below 2-year yields, the market is
pricing cuts ahead — the inversion that has preceded every modern recession.

Cached daily, like the regime that consumes it. Failures are never cached, so a
laptop that was offline at 9am recovers on the next call rather than the next day.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from app.services.ttl_cache import ttl_cache
from app.version import __version__

logger = logging.getLogger(__name__)

# The calendar date is the key, so the curve is refetched once a day whatever
# the clock says. The TTL is only what stops yesterday's entry from lingering.
_CURVE_TTL = 24 * 3600

_FEED_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
_USER_AGENT = f"FolioOrb/{__version__}"

# The feed is an Atom document wrapping OData properties.
_M_NS = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
_D_NS = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"

_TENOR_FIELDS = {
    "1mo": "BC_1MONTH",
    "3mo": "BC_3MONTH",
    "6mo": "BC_6MONTH",
    "1yr": "BC_1YEAR",
    "2yr": "BC_2YEAR",
    "5yr": "BC_5YEAR",
    "10yr": "BC_10YEAR",
    "30yr": "BC_30YEAR",
}

# 2s10s bands in basis points. The flat band is wide enough that a couple of
# basis points of daily noise doesn't flip the label back and forth.
_FLAT_MAX_BPS = 25.0
_STEEP_MIN_BPS = 150.0

# Per-attempt, and there are two attempts (this year, then last). The regime this
# feeds is cached for the whole calendar day, so the cost lands on one request —
# the first load after midnight, where it is a user waiting on a page. Treasury
# either answers promptly or is having an outage; a long patient wait buys
# nothing the day-cached fallback doesn't already cover.
_FETCH_TIMEOUT = 4.0


def _fetch_curve_xml() -> str | None:
    """Fetch the curve feed, falling back a year when January has no data yet."""
    import requests

    year = date.today().year
    for candidate in (year, year - 1):
        try:
            resp = requests.get(
                _FEED_URL.format(year=candidate),
                timeout=_FETCH_TIMEOUT,
                headers={"User-Agent": _USER_AGENT},
            )
            if resp.status_code != 200 or not resp.text:
                continue
            if _parse_curve_xml(resp.text) is None:
                continue  # a fresh year with no business days published yet
            return resp.text
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug(
                "Yield curve fetch failed (%s): %s", candidate, type(exc).__name__
            )
    return None


def _parse_curve_xml(xml_text: str) -> dict | None:
    """Return the most recent entry's tenors, or None if nothing is readable."""
    # ElementTree expands internal entities, so a hostile response on a hijacked
    # connection could blow up the parser. The real feed never declares a DTD.
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        logger.warning("Yield curve feed carried a DTD; refusing to parse it.")
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    newest_date: str | None = None
    newest_tenors: dict[str, float] = {}

    for props in root.iter(f"{_M_NS}properties"):
        raw_date = props.findtext(f"{_D_NS}NEW_DATE")
        if not raw_date:
            continue
        as_of = raw_date.split("T")[0]
        if newest_date is not None and as_of <= newest_date:
            continue
        tenors: dict[str, float] = {}
        for tenor, field in _TENOR_FIELDS.items():
            raw = props.findtext(f"{_D_NS}{field}")
            if raw is None or not raw.strip():
                continue
            try:
                tenors[tenor] = float(raw)
            except ValueError:
                continue  # a tenor the feed left unpriced that day
        newest_date, newest_tenors = as_of, tenors

    if newest_date is None:
        return None
    return {"as_of": newest_date, "tenors": newest_tenors}


def _compute_spreads(tenors: dict[str, float]) -> dict[str, float | None]:
    """The two spreads the market actually watches, in basis points."""

    def _spread(long_leg: str, short_leg: str) -> float | None:
        long_yield, short_yield = tenors.get(long_leg), tenors.get(short_leg)
        if long_yield is None or short_yield is None:
            return None
        return round((long_yield - short_yield) * 100, 1)

    return {
        "spread_2s10s": _spread("10yr", "2yr"),
        "spread_3m10y": _spread("10yr", "3mo"),
    }


def _classify_curve(spread_2s10s: float | None) -> str:
    if spread_2s10s is None:
        return "unknown"
    if spread_2s10s < 0:
        return "inverted"
    if spread_2s10s < _FLAT_MAX_BPS:
        return "flat"
    if spread_2s10s >= _STEEP_MIN_BPS:
        return "steep"
    return "normal"


def _curve_label(curve_state: str, spread_2s10s: float | None) -> str:
    if curve_state == "unknown" or spread_2s10s is None:
        return "Curve unavailable"
    sign = "+" if spread_2s10s >= 0 else "−"
    return f"{curve_state.capitalize()} curve · 2s10s {sign}{abs(spread_2s10s):.0f}bp"


def _unavailable() -> dict:
    return {
        "as_of": None,
        "tenors": {},
        "spread_2s10s": None,
        "spread_3m10y": None,
        "curve_state": "unknown",
        "inverted": None,
        "label": _curve_label("unknown", None),
        "data_quality": "unavailable",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@ttl_cache(
    ttl=_CURVE_TTL,
    key=lambda: date.today().isoformat(),
    # An offline morning shouldn't blank the curve all day, so only a live
    # curve is remembered.
    cache_when=lambda curve: curve["data_quality"] == "live",
    copy=dict,
)
def get_yield_curve() -> dict:
    """Return today's par yield curve, its spreads, and its shape."""
    xml_text = _fetch_curve_xml()
    parsed = _parse_curve_xml(xml_text) if xml_text else None
    if not parsed:
        return _unavailable()

    spreads = _compute_spreads(parsed["tenors"])
    curve_state = _classify_curve(spreads["spread_2s10s"])
    return {
        "as_of": parsed["as_of"],
        "tenors": parsed["tenors"],
        "spread_2s10s": spreads["spread_2s10s"],
        "spread_3m10y": spreads["spread_3m10y"],
        "curve_state": curve_state,
        "inverted": None if curve_state == "unknown" else curve_state == "inverted",
        "label": _curve_label(curve_state, spreads["spread_2s10s"]),
        "data_quality": "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
