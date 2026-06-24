"""Global AI news aggregator — multi-strategy fetching from 20+ sources.

Strategy types:
- RSS/Atom: OpenAI, Anthropic, DeepMind, Google, arXiv, HF, HN, PH, Meta
- GitHub API: Releases from top AI repos (transformers, ollama, vllm, etc.)
- SearXNG: Web/news search for AI topics + X/Twitter AI discussions
- Direct JSON API: Hacker News Algolia

Uses cache + circuit breaker + ThreadPoolExecutor for parallel fetching.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from src.data.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from src.data.http_client import create_session
from src.utils.logger import get_logger

logger = get_logger("data.ai_news_aggregator")

__all__ = ["AiNewsItem", "AiNewsAggregator", "AI_NEWS_SOURCES"]

_CACHE_TTL = 600  # 10 minutes
_FETCH_TIMEOUT = (5.0, 20.0)
_SEARXNG_URL = "http://searxng:8080/search"

# ── Top AI GitHub repos to track releases ────────────────────────────

_GITHUB_AI_REPOS = [
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
    "huggingface/transformers",
    "langchain-ai/langchain",
    "ollama/ollama",
    "vllm-project/vllm",
    "ggml-org/llama.cpp",
    "meta-llama/llama",
    "microsoft/autogen",
    "crewAIInc/crewAI",
    "run-llama/llama_index",
    "Significant-Gravitas/AutoGPT",
    "pytorch/pytorch",
    "keras-team/keras",
]

# ── SearXNG search queries ───────────────────────────────────────────

_SEARXNG_QUERIES = [
    {
        "id": "searx_ai_news",
        "name": "AI News (Web)",
        "q": "OpenAI OR Anthropic OR DeepMind OR Gemini OR ChatGPT OR Claude AI OR LLM",
        "categories": "news",
        "time_range": "week",
        "icon": "🌐",
    },
    {
        "id": "searx_x_ai",
        "name": "X/Twitter AI",
        "q": 'site:x.com (OpenAI OR Anthropic OR DeepMind OR LLM OR GPT OR Claude OR Gemini OR "AI model")',
        "categories": "general",
        "time_range": "week",
        "icon": "𝕏",
    },
    {
        "id": "searx_ai_launches",
        "name": "AI Launches",
        "q": '"AI model" OR "foundation model" OR "open-source AI" OR "open source LLM" OR GPT-5 OR Llama OR Mistral',
        "categories": "news",
        "time_range": "month",
        "icon": "🚀",
    },
]

# Keywords for post-fetch relevance filtering on SearXNG results
_AI_RELEVANCE_KEYWORDS = {
    "ai",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "llm",
    "large language model",
    "gpt",
    "chatgpt",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "deepmind",
    "meta ai",
    "llama",
    "mistral",
    "transformer",
    "neural network",
    "diffusion",
    "stable diffusion",
    "midjourney",
    "copilot",
    "hugging face",
    "pytorch",
    "tensorflow",
    "foundation model",
    "agent",
    "rag",
    "fine-tuning",
    "inference",
    "benchmark",
    "reasoning",
    "multimodal",
    "vision",
    "nlp",
    "robotics",
    "nvidia",
    "gpu",
    "tpu",
    "scaling",
    "alignment",
    "safety",
    "langchain",
    "ollama",
    "vllm",
    "groq",
    "perplexity",
    "cursor",
    "windsurf",
    "devin",
    "sora",
    "dall-e",
    "flux",
}


def _is_ai_relevant(title: str, summary: str) -> bool:
    """Check if content is AI-related based on keyword matching."""
    text = (title + " " + summary).lower()
    return any(kw in text for kw in _AI_RELEVANCE_KEYWORDS)


# ── RSS Source registry ──────────────────────────────────────────────

AI_NEWS_SOURCES: list[dict[str, str]] = [
    {
        "id": "openai",
        "name": "OpenAI Blog",
        "url": "https://openai.com/news/rss.xml",
        "category": "official",
        "format": "rss",
        "icon": "🤖",
    },
    {
        "id": "anthropic",
        "name": "Anthropic News",
        "url": "https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml",
        "category": "official",
        "format": "rss",
        "icon": "🔬",
    },
    {
        "id": "deepmind",
        "name": "Google DeepMind",
        "url": "https://deepmind.google/blog/rss.xml",
        "category": "official",
        "format": "rss",
        "icon": "🧠",
    },
    {
        "id": "google_research",
        "name": "Google Research",
        "url": "https://research.google/blog/rss/",
        "category": "official",
        "format": "rss",
        "icon": "🔍",
    },
    {
        "id": "google_ai",
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "category": "official",
        "format": "rss",
        "icon": "✨",
    },
    {
        "id": "arxiv",
        "name": "arXiv AI/ML/NLP",
        "url": "https://rss.arxiv.org/rss/cs.AI+cs.LG+cs.CL",
        "category": "research",
        "format": "rss",
        "icon": "📄",
    },
    {
        "id": "hf_papers",
        "name": "Hugging Face Papers",
        "url": "https://papers.takara.ai/api/feed",
        "category": "research",
        "format": "rss",
        "icon": "🤗",
    },
    {
        "id": "hf_blog",
        "name": "Hugging Face Blog",
        "url": "https://huggingface.co/blog/feed.xml",
        "category": "official",
        "format": "rss",
        "icon": "🤗",
    },
    {
        "id": "hackernews",
        "name": "Hacker News AI",
        "url": "https://hnrss.org/newest?q=AI+OR+%22artificial+intelligence%22+OR+%22machine+learning%22+OR+LLM+OR+GPT+OR+Claude&points=50&count=30",
        "category": "community",
        "format": "rss",
        "icon": "📰",
    },
    {
        "id": "github_trending",
        "name": "GitHub Trending (Python)",
        "url": "https://mshibanami.github.io/GitHubTrendingRSS/daily/python.xml",
        "category": "github",
        "format": "rss",
        "icon": "⭐",
    },
    {
        "id": "producthunt",
        "name": "Product Hunt AI",
        "url": "https://www.producthunt.com/feed?category=artificial-intelligence",
        "category": "community",
        "format": "atom",
        "icon": "🚀",
    },
    {
        "id": "meta_eng",
        "name": "Meta Engineering",
        "url": "https://engineering.fb.com/feed/",
        "category": "official",
        "format": "rss",
        "icon": "📘",
    },
]

# Namespace map for XML parsing
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


@dataclass
class AiNewsItem:
    """A single AI news item from any source."""

    title: str
    url: str
    summary: str
    source_id: str
    source_name: str
    category: str  # official | research | community | github | search
    published_at: datetime
    icon: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "summary": self.summary[:500],
            "source_id": self.source_id,
            "source_name": self.source_name,
            "category": self.category,
            "published_at": self.published_at.isoformat(),
            "icon": self.icon,
            "tags": self.tags,
        }


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    clean = clean.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return clean.strip()


def _parse_datetime(text: str | None) -> datetime:
    """Best-effort datetime parsing from RSS/Atom date strings."""
    if not text:
        return datetime.now(tz=timezone.utc)
    text = text.strip()
    # RFC 2822 (RSS pubDate)
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc)
    except Exception:
        pass
    # ISO 8601 (Atom)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


def _find_text(el: ET.Element, path: str) -> str:
    """Find text content in an XML element, trying multiple namespace combos."""
    # Try without namespace first
    node = el.find(path)
    if node is not None and node.text:
        return node.text.strip()
    # Try with common namespaces
    for _prefix, uri in _NS.items():
        ns_path = path.replace(path.split("/")[-1], f"{{{uri}}}{path.split('/')[-1]}")
        node = el.find(ns_path)
        if node is not None and node.text:
            return node.text.strip()
    return ""


class AiNewsAggregator:
    """Fetch and parse AI news from multiple sources (RSS + API + SearXNG).

    Usage::

        agg = AiNewsAggregator()
        items = agg.fetch_all()                    # all sources
        items = agg.fetch_source("openai")         # single source
        items = agg.fetch_by_category("official")  # by category
    """

    def __init__(self, sources: list[dict[str, str]] | None = None) -> None:
        self._sources = sources or AI_NEWS_SOURCES
        self._session = create_session(timeout=_FETCH_TIMEOUT, retries=2)
        self._cache: dict[str, tuple[float, list[AiNewsItem]]] = {}
        self._circuits: dict[str, CircuitBreaker] = {}
        # Build a combined source list (RSS + GitHub + SearXNG)
        self._all_source_ids: list[dict[str, str]] = []
        for src in self._sources:
            self._circuits[src["id"]] = CircuitBreaker(
                f"ai_news_{src['id']}",
                failure_threshold=3,
                recovery_timeout=600.0,
            )
            self._all_source_ids.append(src)
        # GitHub releases as virtual source
        self._circuits["github_releases"] = CircuitBreaker(
            "ai_news_github_releases",
            failure_threshold=3,
            recovery_timeout=600.0,
        )
        self._all_source_ids.append(
            {
                "id": "github_releases",
                "name": "GitHub AI Releases",
                "category": "github",
                "icon": "📦",
                "url": "https://api.github.com",
            }
        )
        # SearXNG search sources
        for sq in _SEARXNG_QUERIES:
            sid = sq["id"]
            self._circuits[sid] = CircuitBreaker(
                f"ai_news_{sid}",
                failure_threshold=3,
                recovery_timeout=600.0,
            )
            self._all_source_ids.append(
                {
                    "id": sid,
                    "name": sq["name"],
                    "category": "search",
                    "icon": sq["icon"],
                    "url": _SEARXNG_URL,
                }
            )

    def _get_cache(self, key: str) -> list[AiNewsItem] | None:
        if key in self._cache:
            expire_ts, items = self._cache[key]
            if time.time() < expire_ts:
                return items
        return None

    def _set_cache(self, key: str, items: list[AiNewsItem]) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, items)

    # ── RSS/Atom parsers ─────────────────────────────────────────────

    def _parse_rss(self, xml_text: str, source: dict[str, str]) -> list[AiNewsItem]:
        """Parse RSS 2.0 feed."""
        items: list[AiNewsItem] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("RSS parse error for %s: %s", source["id"], e)
            return items

        for item_el in root.iter("item"):
            title = _find_text(item_el, "title") or "(untitled)"
            link = _find_text(item_el, "link")
            if not link:
                link = _find_text(item_el, "guid")
            desc = _find_text(item_el, "description")
            content = _find_text(item_el, "content:encoded")
            summary = _strip_html(content or desc)[:500]
            pub_date = _find_text(item_el, "pubDate") or _find_text(item_el, "dc:date")

            items.append(
                AiNewsItem(
                    title=_strip_html(title),
                    url=link,
                    summary=summary,
                    source_id=source["id"],
                    source_name=source["name"],
                    category=source["category"],
                    published_at=_parse_datetime(pub_date),
                    icon=source.get("icon", ""),
                )
            )
        return items

    def _parse_atom(self, xml_text: str, source: dict[str, str]) -> list[AiNewsItem]:
        """Parse Atom 1.0 feed."""
        items: list[AiNewsItem] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("Atom parse error for %s: %s", source["id"], e)
            return items

        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.iter(f"{ns}entry"):
            title_el = entry.find(f"{ns}title")
            title = (
                (title_el.text or "(untitled)").strip()
                if title_el is not None
                else "(untitled)"
            )

            link = ""
            for link_el in entry.findall(f"{ns}link"):
                rel = link_el.get("rel", "alternate")
                if rel == "alternate":
                    link = link_el.get("href", "")
                    break
            if not link:
                link_el = entry.find(f"{ns}link")
                if link_el is not None:
                    link = link_el.get("href", "")

            summary_el = entry.find(f"{ns}summary")
            content_el = entry.find(f"{ns}content")
            summary = _strip_html(
                (
                    content_el.text
                    if content_el is not None and content_el.text
                    else None
                )
                or (
                    summary_el.text
                    if summary_el is not None and summary_el.text
                    else ""
                )
            )[:500]

            updated_el = entry.find(f"{ns}updated")
            published_el = entry.find(f"{ns}published")
            date_str = None
            if published_el is not None and published_el.text:
                date_str = published_el.text
            elif updated_el is not None and updated_el.text:
                date_str = updated_el.text

            items.append(
                AiNewsItem(
                    title=_strip_html(title),
                    url=link,
                    summary=summary,
                    source_id=source["id"],
                    source_name=source["name"],
                    category=source["category"],
                    published_at=_parse_datetime(date_str),
                    icon=source.get("icon", ""),
                )
            )
        return items

    # ── GitHub releases fetcher ──────────────────────────────────────

    def _fetch_github_releases(self) -> list[AiNewsItem]:
        """Fetch latest releases from top AI repos via GitHub API."""
        items: list[AiNewsItem] = []
        for repo in _GITHUB_AI_REPOS:
            try:
                resp = self._session.get(
                    f"https://api.github.com/repos/{repo}/releases",
                    params={"per_page": 3},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "AINewsAggregator/1.0",
                    },
                    timeout=10,
                )
                if resp.status_code == 403:
                    logger.warning("GitHub rate limit hit for %s", repo)
                    break
                if resp.status_code != 200:
                    continue
                releases = resp.json()
                if not isinstance(releases, list):
                    continue
                for rel in releases[:3]:
                    tag = rel.get("tag_name", "")
                    name = rel.get("name") or tag
                    body = _strip_html(rel.get("body", ""))[:500]
                    pub = rel.get("published_at") or rel.get("created_at", "")
                    html_url = rel.get("html_url", f"https://github.com/{repo}")

                    items.append(
                        AiNewsItem(
                            title=f"{repo} {name}",
                            url=html_url,
                            summary=body,
                            source_id="github_releases",
                            source_name="GitHub AI Releases",
                            category="github",
                            published_at=_parse_datetime(pub),
                            icon="📦",
                            tags=[repo.split("/")[0], tag],
                        )
                    )
                # Polite rate limiting
                time.sleep(0.2)
            except Exception:
                logger.debug("GitHub release fetch failed for %s", repo, exc_info=True)
        return items

    # ── SearXNG search fetcher ───────────────────────────────────────

    def _fetch_searxng(self, query_config: dict[str, str]) -> list[AiNewsItem]:
        """Fetch AI news via SearXNG meta-search."""
        items: list[AiNewsItem] = []
        try:
            resp = self._session.get(
                _SEARXNG_URL,
                params={
                    "q": query_config["q"],
                    "format": "json",
                    "categories": query_config.get("categories", "news"),
                    "time_range": query_config.get("time_range", "week"),
                    "language": "en",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])

            for r in results[:50]:
                title = r.get("title", "(untitled)")
                url = r.get("url", "")
                content = _strip_html(r.get("content", ""))[:500]
                pub = r.get("publishedDate")
                engine = r.get("engine", "")

                # Filter out non-AI content
                if not _is_ai_relevant(title, content):
                    continue

                items.append(
                    AiNewsItem(
                        title=title,
                        url=url,
                        summary=content,
                        source_id=query_config["id"],
                        source_name=query_config["name"],
                        category="search",
                        published_at=_parse_datetime(pub),
                        icon=query_config.get("icon", "🌐"),
                        tags=[engine] if engine else [],
                    )
                )
        except Exception:
            logger.exception(
                "SearXNG fetch failed for %s", query_config.get("id", "unknown")
            )
        return items

    # ── Unified fetch dispatch ───────────────────────────────────────

    def fetch_source(self, source_id: str) -> list[AiNewsItem]:
        """Fetch items from a single source (any strategy)."""
        cached = self._get_cache(source_id)
        if cached is not None:
            return cached

        cb = self._circuits.get(source_id)

        # Dispatch to the right fetcher
        if source_id == "github_releases":
            fetcher_fn = self._fetch_github_releases
        elif source_id.startswith("searx_"):
            query_cfg = next(
                (sq for sq in _SEARXNG_QUERIES if sq["id"] == source_id), None
            )
            if not query_cfg:
                return []
            fetcher_fn = lambda: self._fetch_searxng(query_cfg)  # noqa: E731
        else:
            # RSS/Atom source
            source = next((s for s in self._sources if s["id"] == source_id), None)
            if not source:
                logger.warning("Unknown AI news source: %s", source_id)
                return []

            def fetcher_fn() -> list[AiNewsItem]:
                resp = self._session.get(
                    source["url"],
                    headers={
                        "User-Agent": "AINewsAggregator/1.0 (+https://github.com)",
                        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                    },
                )
                resp.raise_for_status()
                xml_text = resp.text

                if source.get("format") == "atom":
                    result = self._parse_atom(xml_text, source)
                else:
                    result = self._parse_rss(xml_text, source)
                    if not result:
                        result = self._parse_atom(xml_text, source)
                return result

        try:
            if cb:
                items = cb.call(fetcher_fn)
            else:
                items = fetcher_fn()

            self._set_cache(source_id, items)
            logger.info("Fetched %d items from %s", len(items), source_id)
            return items

        except CircuitBreakerOpen:
            logger.debug("Circuit open for %s, skipping", source_id)
            return []
        except Exception:
            logger.exception("Failed to fetch AI news from %s", source_id)
            return []

    def fetch_all(self, limit_per_source: int = 20) -> list[AiNewsItem]:
        """Fetch from all sources in parallel, merge and sort by date descending."""
        all_items: list[AiNewsItem] = []
        all_ids = [s["id"] for s in self._all_source_ids]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(self.fetch_source, sid): sid for sid in all_ids}
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    items = future.result(timeout=60)
                    all_items.extend(items[:limit_per_source])
                except Exception:
                    logger.warning("Parallel fetch failed for %s", sid)

        # Sort by published date descending
        all_items.sort(key=lambda x: x.published_at, reverse=True)
        return all_items

    def fetch_by_category(
        self, category: str, limit_per_source: int = 20
    ) -> list[AiNewsItem]:
        """Fetch from sources in a specific category (parallel)."""
        source_ids = [
            s["id"] for s in self._all_source_ids if s["category"] == category
        ]
        items: list[AiNewsItem] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(self.fetch_source, sid): sid for sid in source_ids}
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    fetched = future.result(timeout=60)
                    items.extend(fetched[:limit_per_source])
                except Exception:
                    logger.warning("Parallel fetch failed for %s", sid)
        items.sort(key=lambda x: x.published_at, reverse=True)
        return items

    def get_source_status(self) -> list[dict[str, Any]]:
        """Return status of each source (cached count, circuit state)."""
        statuses = []
        for source in self._all_source_ids:
            sid = source["id"]
            cached = self._get_cache(sid)
            cb = self._circuits.get(sid)
            statuses.append(
                {
                    "id": sid,
                    "name": source["name"],
                    "category": source["category"],
                    "icon": source.get("icon", ""),
                    "url": source.get("url", ""),
                    "cached_count": len(cached) if cached else 0,
                    "circuit_open": bool(cb and cb.state == "open"),
                }
            )
        return statuses
