"""Build the RAG index for Copernicus Berlin.

Crawls copernicusberlin.org/en/* with a headless Chromium browser,
embeds the page content with OpenAI, and writes the index to data/index/.
"""
from __future__ import annotations

from app.services.indexer import build_index


def main() -> None:
    docs, chunks = build_index(full_crawl=True)
    print(f"Indexed {docs} documents into {chunks} chunks.")


if __name__ == "__main__":
    main()
