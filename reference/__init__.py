"""
MQL5 Reference Module

Provides indexed access to the 7000-page MQL5 reference PDF.

Usage:
    from reference import mql5_search, mql5_lookup

    # Search for topics
    results = mql5_search("order history")

    # Get documentation
    docs = mql5_lookup("CopyRates")
"""

from reference.lookup import (
    mql5_search,
    mql5_lookup,
    mql5_pages,
    mql5_sections,
    quick_lookup,
    COMMON_TOPICS,
)

__all__ = [
    'mql5_search',
    'mql5_lookup',
    'mql5_pages',
    'mql5_sections',
    'quick_lookup',
    'COMMON_TOPICS',
]
