from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings


@dataclass
class PageDocument:
    url: str
    language: str
    title: str
    text: str


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned = parsed._replace(fragment="", query="")
    normalized = urlunparse(cleaned)
    if normalized.endswith("/") and len(normalized) > len(f"{parsed.scheme}://{parsed.netloc}/"):
        normalized = normalized[:-1]
    return normalized


def _fetch_sitemap_urls(client: httpx.Client, root: str) -> list[str]:
    sitemap_url = f"{root}/sitemap.xml"
    try:
        res = client.get(sitemap_url)
    except Exception:
        return []
    if res.status_code != 200:
        return []
    soup = BeautifulSoup(res.text, "xml")
    urls: list[str] = []
    for loc in soup.find_all("loc"):
        if not loc.text:
            continue
        raw = loc.text.strip()
        # sitemap may contain dev hostnames (localhost). Rewrite to real host.
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            real = f"{urlparse(root).scheme}://{urlparse(root).netloc}{parsed.path}"
        else:
            real = urljoin(root + "/", raw.lstrip("/"))
        urls.append(_normalize_url(real))
    return urls


def _extract_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    title_tag = soup.title
    title = title_tag.string.strip() if title_tag and title_tag.string else ""
    # Strip headers/footers/nav from rendered body so we don't index repeating chrome.
    for sel in ("header", "nav", "footer", "aside"):
        for el in soup.select(sel):
            el.decompose()
    main = soup.select_one("main") or soup.select_one("article") or soup.body or soup
    lines = [ln.strip() for ln in main.get_text("\n").splitlines() if ln.strip()]
    return "\n".join(lines), title


def _drop_repeated_lines(docs: list[PageDocument]) -> list[PageDocument]:
    if not docs:
        return docs
    freq: dict[str, int] = {}
    for d in docs:
        for line in {ln.strip() for ln in d.text.splitlines() if ln.strip()}:
            freq[line] = freq.get(line, 0) + 1
    threshold = max(8, int(len(docs) * 0.5))
    cleaned: list[PageDocument] = []
    for d in docs:
        kept: list[str] = []
        for line in d.text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) <= 120 and freq.get(stripped, 0) >= threshold:
                continue
            kept.append(stripped)
        cleaned.append(PageDocument(url=d.url, language=d.language, title=d.title, text="\n".join(kept)))
    return cleaned


def _link_is_allowed(url: str, root_netloc: str, excluded_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return False
    if parsed.netloc != root_netloc:
        return False
    host = parsed.netloc.lower()
    if any(host == h or host.endswith(f".{h}") for h in excluded_hosts):
        return False
    # Only English routes.
    if not (parsed.path == "/en" or parsed.path.startswith("/en/")):
        return False
    return True


def crawl_site() -> list[PageDocument]:
    """Crawl copernicusberlin.org/en with a headless browser to render the React SPA."""
    from playwright.sync_api import sync_playwright

    root = settings.site_root.strip().rstrip("/")
    if not root:
        raise RuntimeError("SITE_ROOT is required")

    root_parsed = urlparse(root)
    root_netloc = root_parsed.netloc
    excluded_hosts = {h.strip().lower() for h in settings.crawl_exclude_hosts.split(",") if h.strip()}

    starts: list[str] = []
    for p in settings.crawl_paths.split(","):
        p = p.strip()
        if not p:
            continue
        starts.append(_normalize_url(root + (p if p.startswith("/") else "/" + p)))

    # Discover URLs from the sitemap up front.
    discovered: list[str] = []
    with httpx.Client(timeout=settings.crawl_timeout_sec, follow_redirects=True) as client:
        for u in _fetch_sitemap_urls(client, root):
            if _link_is_allowed(u, root_netloc, excluded_hosts):
                discovered.append(u)

    seen: set[str] = set()
    queue: deque[str] = deque()
    for u in starts + discovered:
        nu = _normalize_url(u)
        if nu not in seen:
            queue.append(nu)
            seen.add(nu)

    docs: list[PageDocument] = []
    wait_ms = max(500, int(settings.crawl_render_wait_ms))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (compatible; CopernicusBerlinBot/1.0)",
            viewport={"width": 1280, "height": 1800},
        )
        page = ctx.new_page()
        while queue:
            if settings.crawl_max_pages > 0 and len(docs) >= settings.crawl_max_pages:
                break
            current = queue.popleft()
            try:
                page.goto(current, wait_until="networkidle", timeout=int(settings.crawl_timeout_sec * 1000))
            except Exception:
                try:
                    page.goto(current, wait_until="domcontentloaded", timeout=int(settings.crawl_timeout_sec * 1000))
                except Exception:
                    continue
            try:
                page.wait_for_timeout(wait_ms)
            except Exception:
                pass
            try:
                html = page.content()
            except Exception:
                continue

            text, title = _extract_text(html)
            if text and len(text) > 80:
                docs.append(PageDocument(url=current, language="en", title=title, text=text))
                print(f"[crawl] {current} — {len(text)} chars")

            # Discover same-host /en links.
            for m in re.finditer(r'href="([^"]+)"', html):
                href = m.group(1)
                if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
                    continue
                nxt = _normalize_url(urljoin(current, href))
                if _link_is_allowed(nxt, root_netloc, excluded_hosts) and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

        ctx.close()
        browser.close()

    return _drop_repeated_lines(docs)
