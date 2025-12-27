"""
Quick MQL5 Reference Lookup

Simple interface for extracting documentation from the MQL5 reference.
Use this module to get authoritative MQL5 documentation for any topic.

Example:
    from reference.lookup import mql5_lookup, mql5_search

    # Search for topics
    results = mql5_search("order send")

    # Get full documentation for a topic
    docs = mql5_lookup("OrderSend")
"""

from pathlib import Path

# Lazy import to avoid loading on every import
_ref = None

def _get_ref():
    global _ref
    if _ref is None:
        from reference.mql5_indexer import MQL5Reference
        _ref = MQL5Reference()
    return _ref


def mql5_search(query: str, max_results: int = 10) -> list:
    """
    Search the MQL5 reference for topics matching query.

    Args:
        query: Search terms (e.g., "order history", "copy rates", "position")
        max_results: Maximum number of results to return

    Returns:
        List of dicts with 'title', 'pages', 'score' keys
    """
    ref = _get_ref()
    results = ref.search(query, max_results)
    return [
        {'title': r['title'], 'pages': r['pages'], 'score': r['score']}
        for r in results
    ]


def mql5_lookup(topic: str, max_pages: int = 20) -> str:
    """
    Get full documentation for a topic from the MQL5 reference.

    Args:
        topic: Topic to look up (e.g., "CopyRates", "OrderSend", "CTrade")
        max_pages: Maximum pages to extract (default 20)

    Returns:
        Extracted text from the reference
    """
    ref = _get_ref()
    return ref.get_topic(topic, max_pages)


def mql5_pages(start: int, end: int) -> str:
    """
    Extract specific pages from the reference.

    Args:
        start: Start page number
        end: End page number

    Returns:
        Extracted text from specified pages
    """
    ref = _get_ref()
    return ref.extract_pages(start, end)


def mql5_sections(level: int = 2) -> list:
    """
    List major sections of the reference.

    Args:
        level: Maximum heading level (1=top only, 2=major sections, 3=subsections)

    Returns:
        List of section titles with page numbers
    """
    ref = _get_ref()
    return ref.list_sections(level)


# Common lookup shortcuts
COMMON_TOPICS = {
    'trade': 'Trade Functions',
    'order': 'OrderSend',
    'position': 'PositionSelect',
    'history': 'HistorySelect',
    'rates': 'CopyRates',
    'indicator': 'Custom Indicators',
    'buffer': 'CopyBuffer',
    'chart': 'Chart Operations',
    'account': 'Account Information',
    'symbol': 'SymbolInfoDouble',
    'file': 'File Functions',
    'datetime': 'Date and Time',
    'array': 'Array Functions',
    'math': 'Math Functions',
    'string': 'String Functions',
    'event': 'Event Handling',
    'ctrade': 'CTrade',
    'cposition': 'CPositionInfo',
    'corder': 'COrderInfo',
    'cdeal': 'CDealInfo',
}


def quick_lookup(shortcut: str) -> str:
    """
    Quick lookup using common shortcuts.

    Args:
        shortcut: One of: trade, order, position, history, rates, indicator, etc.

    Returns:
        Documentation for the topic
    """
    topic = COMMON_TOPICS.get(shortcut.lower(), shortcut)
    return mql5_lookup(topic)


if __name__ == "__main__":
    # Quick test
    print("MQL5 Reference Quick Lookup")
    print("=" * 40)
    print("\nSearching for 'order send':")
    for r in mql5_search("order send", 5):
        print(f"  [{r['score']:2d}] {r['title']} (p.{r['pages']})")
