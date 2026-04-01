"""Thin wrapper around crawl4ai for fetching JS-rendered pages."""
import asyncio
import random

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig


async def fetch_page_content(url: str) -> str:
    """Fetch a URL and return cleaned markdown. Returns empty string on failure."""
    config = CrawlerRunConfig(
        word_count_threshold=10,
        remove_overlay_elements=True,
        page_timeout=30000,
    )
    try:
        # Polite random delay before each request
        await asyncio.sleep(random.uniform(1.0, 3.0))
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
            if result.success:
                # crawl4ai 0.4.x exposes markdown as a result object
                md = result.markdown
                if hasattr(md, "raw_markdown"):
                    return md.raw_markdown or ""
                return str(md) if md else ""
    except Exception as e:
        print(f"fetch_page_content failed for {url}: {e}")
    return ""
