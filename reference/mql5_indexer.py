"""
MQL5 Reference Indexer and Lookup System

Provides indexed access to the 7000-page MQL5 reference PDF.
Extracts sections on-demand to avoid loading the entire document.
"""

import json
import re
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    raise ImportError("Install PyMuPDF: pip install pymupdf")


class MQL5Reference:
    """Indexed access to MQL5 reference documentation."""

    def __init__(self, pdf_path: Optional[str] = None):
        self.project_root = Path(__file__).parent.parent
        self.pdf_path = Path(pdf_path) if pdf_path else self.project_root / "mql5.pdf"
        self.index_path = self.project_root / "reference" / "mql5_index.json"
        self.cache_dir = self.project_root / "reference" / "cache"

        self._index = None
        self._doc = None

    @property
    def index(self) -> dict:
        """Lazy-load the index."""
        if self._index is None:
            if self.index_path.exists():
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
            else:
                self._index = self.build_index()
        return self._index

    @property
    def doc(self):
        """Lazy-load the PDF document."""
        if self._doc is None:
            self._doc = fitz.open(str(self.pdf_path))
        return self._doc

    def build_index(self) -> dict:
        """Build searchable index from PDF table of contents."""
        print(f"Building index from {self.pdf_path}...")

        doc = self.doc
        toc = doc.get_toc()
        total_pages = len(doc)

        # Build hierarchical index with page ranges
        entries = []
        for i, (level, title, start_page) in enumerate(toc):
            # Find end page (next entry at same or higher level)
            end_page = total_pages
            for j in range(i + 1, len(toc)):
                next_level, _, next_start = toc[j]
                if next_level <= level:
                    end_page = next_start - 1
                    break

            entries.append({
                'title': title,
                'level': level,
                'start_page': start_page,
                'end_page': end_page,
                'keywords': self._extract_keywords(title)
            })

        # Build keyword lookup table
        keyword_index = {}
        for idx, entry in enumerate(entries):
            for keyword in entry['keywords']:
                if keyword not in keyword_index:
                    keyword_index[keyword] = []
                keyword_index[keyword].append(idx)

        index = {
            'total_pages': total_pages,
            'total_entries': len(entries),
            'entries': entries,
            'keywords': keyword_index,
            'major_sections': self._get_major_sections(entries)
        }

        # Save index
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2)

        print(f"Index saved: {len(entries)} entries, {len(keyword_index)} keywords")
        return index

    def _extract_keywords(self, title: str) -> list:
        """Extract searchable keywords from a title."""
        # Clean and split
        title_lower = title.lower()
        # Split on non-alphanumeric
        words = re.findall(r'[a-z0-9]+', title_lower)
        # Filter very short words
        words = [w for w in words if len(w) > 2]
        # Add common variations
        keywords = set(words)

        # Add the full title as a keyword too
        keywords.add(title_lower.replace(' ', '_'))

        return list(keywords)

    def _get_major_sections(self, entries: list) -> list:
        """Get top-level sections for quick navigation."""
        return [
            {'title': e['title'], 'start': e['start_page'], 'end': e['end_page']}
            for e in entries if e['level'] <= 2
        ]

    def search(self, query: str, max_results: int = 20) -> list:
        """Search for topics matching query."""
        query_terms = query.lower().split()
        results = []

        for idx, entry in enumerate(self.index['entries']):
            title_lower = entry['title'].lower()

            # Score by how many query terms match
            score = 0
            for term in query_terms:
                if term in title_lower:
                    score += 10  # Title contains term
                if term in entry['keywords']:
                    score += 5  # Keyword match
                # Partial match
                for kw in entry['keywords']:
                    if term in kw or kw in term:
                        score += 2

            if score > 0:
                results.append({
                    'score': score,
                    'title': entry['title'],
                    'level': entry['level'],
                    'pages': f"{entry['start_page']}-{entry['end_page']}",
                    'index': idx
                })

        # Sort by score descending
        results.sort(key=lambda x: (-x['score'], x['level']))
        return results[:max_results]

    def get_section(self, entry_index: int) -> str:
        """Extract text content for a specific section."""
        entry = self.index['entries'][entry_index]
        return self.extract_pages(entry['start_page'], entry['end_page'])

    def extract_pages(self, start: int, end: int, max_pages: int = 50) -> str:
        """Extract text from a page range."""
        doc = self.doc

        # Limit extraction to prevent huge outputs
        actual_end = min(end, start + max_pages - 1)

        text_parts = []
        # PDF pages are 0-indexed, but TOC uses 1-indexed
        for page_num in range(start - 1, actual_end):
            if 0 <= page_num < len(doc):
                page = doc[page_num]
                text = page.get_text()
                text_parts.append(f"\n--- Page {page_num + 1} ---\n{text}")

        return "\n".join(text_parts)

    def get_topic(self, topic: str, max_pages: int = 30) -> str:
        """Search for a topic and extract its content."""
        results = self.search(topic, max_results=1)
        if not results:
            return f"No results found for: {topic}"

        best = results[0]
        entry = self.index['entries'][best['index']]

        header = f"=== {entry['title']} (Pages {entry['start_page']}-{entry['end_page']}) ===\n"
        content = self.extract_pages(entry['start_page'], entry['end_page'], max_pages)

        return header + content

    def list_sections(self, level: int = 2) -> list:
        """List all sections up to given level."""
        return [
            f"[{e['start_page']:4d}] {'  ' * (e['level']-1)}{e['title']}"
            for e in self.index['entries']
            if e['level'] <= level
        ]

    def close(self):
        """Close the PDF document."""
        if self._doc:
            self._doc.close()
            self._doc = None


def main():
    """CLI for MQL5 reference lookup."""
    import sys

    ref = MQL5Reference()

    if len(sys.argv) < 2:
        print("MQL5 Reference Lookup")
        print("=" * 40)
        print(f"Indexed: {ref.index['total_entries']} entries, {ref.index['total_pages']} pages")
        print("\nUsage:")
        print("  python mql5_indexer.py search <query>  - Search for topics")
        print("  python mql5_indexer.py get <topic>     - Get content for topic")
        print("  python mql5_indexer.py sections        - List major sections")
        print("  python mql5_indexer.py rebuild         - Rebuild index")
        return

    cmd = sys.argv[1]

    if cmd == "rebuild":
        ref._index = None
        if ref.index_path.exists():
            ref.index_path.unlink()
        ref.build_index()

    elif cmd == "sections":
        for line in ref.list_sections():
            print(line)

    elif cmd == "search" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        results = ref.search(query)
        print(f"Results for '{query}':")
        for r in results:
            print(f"  [{r['score']:2d}] {r['title']} (p.{r['pages']})")

    elif cmd == "get" and len(sys.argv) > 2:
        topic = " ".join(sys.argv[2:])
        print(ref.get_topic(topic))

    else:
        print(f"Unknown command: {cmd}")

    ref.close()


if __name__ == "__main__":
    main()
