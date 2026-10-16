"""Unit conversion utilities for environmental normalization."""

from __future__ import annotations


def kmh_to_mps(kmh: float) -> float:
    """Convert kilometres per hour to metres per second."""
    return kmh / 3.6


def mps_to_kmh(mps: float) -> float:
    """Convert metres per second to kilometres per hour."""
    return mps * 3.6


def knots_to_mps(knots: float) -> float:
    """Convert knots to metres per second."""
    return knots * 0.514444


def celsius_to_kelvin(c: float) -> float:
    """Convert Celsius to Kelvin."""
    return c + 273.15


def location_bucket(lat: float, lon: float, precision: int = 2) -> str:
    """Return a grid-aligned string bucket for geographic cache keys.

    Rounding to 2 decimal places gives an ~1.1 km grid cell.
    This balances cache reuse against geographic specificity.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        precision: Decimal places to round to (default 2 ≈ 1.1 km).

    Returns:
        String in the form ``"<rounded_lat>:<rounded_lon>"``.
    """
    return f"{round(lat, precision)}:{round(lon, precision)}"
