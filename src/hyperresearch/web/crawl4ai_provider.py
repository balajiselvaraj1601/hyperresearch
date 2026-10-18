"""Crawl4AI web provider — free, open-source, local headless browser, returns clean markdown.

Supports authenticated crawling via crawl4ai browser profiles:
  1. Run `crwl profiles` or `hyperresearch setup` to create a profile and log in
  2. Set `profile = "profile-name"` in .hyperresearch/config.toml
  3. All fetches now use your authenticated session (cookies, localStorage, etc.)
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
import threading
from datetime import UTC, datetime

from crawl4ai import (  # type: ignore[import-untyped]
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
)
from crawl4ai.async_crawler_strategy import (  # type: ignore[import-untyped]
    AsyncPlaywrightCrawlerStrategy,  # type: ignore[import-untyped]
)
from crawl4ai.browser_adapter import UndetectedAdapter  # type: ignore[import-untyped]
from crawl4ai.content_filter_strategy import PruningContentFilter  # type: ignore[import-untyped]

from hyperresearch.core.config import FetchSettings, JunkGates
from hyperresearch.web.base import WebResult, is_binary_garbage
from hyperresearch.web.pdf import PDF_FAILURE_KEY
from hyperresearch.web.pdf import failure_reason as _pdf_failure_reason
from hyperresearch.web.pdf import fetch_pdf as _fetch_pdf
from hyperresearch.web.pdf import is_pdf_url as _is_pdf_url

# Fix Windows encoding before crawl4ai's managed browser tries to log Unicode
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            except Exception:
                pass


def _run_coro(coro):
    """Run ``coro`` to completion, whether or not this thread already has a running
    event loop (the MCP server dispatches sync tools on its own loop's thread; the
    CLI does not). A plain ``asyncio.run(coro)`` only works in the second case, so
    fall back to a dedicated thread, which has no running loop of its own.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict = {}

    def _target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # re-raised on the caller's thread below
            box["error"] = exc

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _looks_like_binary(text: str, gates: JunkGates | None = None) -> bool:
    """Check if extracted 'content' is actually binary garbage from a PDF."""
    if not text:
        return False
    gates = gates or JunkGates()
    sample = text[: gates.sample_window]
    # PDF internal structure markers — dead giveaway
    pdf_markers = ("endstream", "endobj", "/Filter", "/FlateDecode", "stream\nx", "%PDF-")
    if any(m in sample for m in pdf_markers):
        return True
    # Shared with WebResult.looks_like_junk() \u2014 keep one implementation, since these
    # two gates drifting apart is what let `ord(c) > 127` survive in base.py and
    # silently discard every non-English page.
    return is_binary_garbage(sample, gates)


def _smart_wait_js(settings: FetchSettings) -> str:
    """DOM-stability polling loop shared by the headless and visible paths.

    Waits `wait_initial_ms`, then polls every `poll_interval_ms` until body text
    length is unchanged for `stable_checks` consecutive polls, giving up after
    `max_checks` polls.
    """
    return (
        "() => new Promise(r => {"
        "  setTimeout(() => {"
        "    let last = document.body.innerText.length;"
        "    let stable = 0;"
        "    let checks = 0;"
        "    const interval = setInterval(() => {"
        "      const now = document.body.innerText.length;"
        "      if (now === last) { stable++; } else { stable = 0; }"
        f"      if (stable >= {settings.stable_checks} || checks > {settings.max_checks}) {{ clearInterval(interval); r(true); }}"
        "      last = now; checks++;"
        f"    }}, {settings.poll_interval_ms});"
        f"  }}, {settings.wait_initial_ms});"
        "})"
    )


def _check_final_url(entry_url: str, final_url: str | None, settings: FetchSettings) -> None:
    """Re-validate the URL the browser actually ended up on.

    The browser follows redirects internally, so the entry-point gate only
    vouches for where navigation STARTED. Refusing after the fact cannot
    stop a request that already fired (blind SSRF survives), but it keeps
    private-network content out of the vault. Skipped when the final host
    equals the entry host — the entry gate already vouched for it, and the
    extra ``getaddrinfo`` would be pure cost on the no-redirect common case.
    """
    from urllib.parse import urlparse

    from hyperresearch.web.safe_http import SafeHTTPError, check_url

    if not final_url or final_url == entry_url:
        return
    entry_host = urlparse(entry_url).hostname
    parsed_final = urlparse(final_url)
    if parsed_final.hostname == entry_host and parsed_final.scheme.lower() in ("http", "https"):
        return
    try:
        check_url(final_url, settings.allow_private_hosts)
    except SafeHTTPError as exc:
        raise SafeHTTPError(
            f"browser navigation for {entry_url!r} ended at refused URL: {exc}"
        ) from exc


def _extract_markdown(md) -> str:
    # result.markdown is a MarkdownGenerationResult with .raw_markdown,
    # .fit_markdown, .markdown_with_citations, etc.
    # Prefer fit_markdown (main content, no nav/footer chrome) over raw_markdown.
    if md and hasattr(md, "fit_markdown"):
        return md.fit_markdown or md.raw_markdown or ""
    if md and hasattr(md, "raw_markdown"):
        return md.raw_markdown or ""
    if isinstance(md, str):
        return md
    return ""


def _extract_media(result) -> list:
    media_raw = result.media or {}
    return media_raw.get("images", []) if isinstance(media_raw, dict) else []


def _extract_links(links_raw) -> list:
    links = []
    if isinstance(links_raw, dict):
        for link in links_raw.get("internal", []):
            links.append({**link, "type": "internal"})
        for link in links_raw.get("external", []):
            links.append({**link, "type": "external"})
    return links


def _decode_screenshot(screenshot):
    if not screenshot:
        return None
    import base64

    try:
        return base64.b64decode(screenshot)
    except Exception:
        return None


def _make_web_result(
    url: str, metadata: dict, content: str, html, media: list, screenshot, links: list | None = None
) -> WebResult:
    return WebResult(
        url=url,
        title=metadata.get("title", ""),
        content=content,
        raw_html=html,
        fetched_at=datetime.now(UTC),
        metadata=metadata,
        media=media,
        links=links or [],
        screenshot=screenshot,
    )


def _gate_batch_urls(urls: list, settings, log) -> list:
    # SSRF gate: same entry-point check as fetch(). Refused URLs are
    # skipped (logged), not fatal — one hostile URL must not kill the
    # whole batch.
    from hyperresearch.web.safe_http import SafeHTTPError, check_url

    allowed_urls = []
    for url in urls:
        try:
            check_url(url, settings.allow_private_hosts)
            allowed_urls.append(url)
        except SafeHTTPError as exc:
            log.warning("refused batch fetch for %s: %s", url, exc)
    return allowed_urls


def _fetch_batch_pdfs(pdf_urls: list, settings, log) -> tuple:
    # Fetch PDFs directly (no browser needed). When _fetch_pdf returns
    # None (parser failure, non-PDF body served at a .pdf URL) we fall
    # back to the browser path — mirrors the single-fetch behaviour in
    # fetch() so batch callers don't silently lose academic PDFs that
    # need JS-rendered landing pages. Cert refusals are the exception:
    # the browser lane ignores TLS errors, so falling back would be an
    # automatic unverified retry. A batch has no per-URL failure
    # channel, so the skip is logged loudly instead.
    from hyperresearch.web.safe_http import CertVerificationError

    web_results = []
    failed_pdf_urls = []
    for url in pdf_urls:
        try:
            pdf_result = _fetch_pdf(url, settings)
        except CertVerificationError as exc:
            log.warning(
                "SKIPPED (TLS certificate invalid): %s -- a potentially "
                "valuable source was not fetched. To include it, set "
                "pdf_verify_tls = false under [fetch] in config.toml. (%s)",
                url,
                exc,
            )
            continue
        if pdf_result is not None:
            web_results.append(pdf_result)
        else:
            failed_pdf_urls.append(url)
    return web_results, failed_pdf_urls


def _fetch_binary_pdf(url: str, settings, log):
    # Post-fetch binary check fallback — browser may have fetched a PDF inline.
    from hyperresearch.web.safe_http import CertVerificationError

    try:
        return _fetch_pdf(url, settings)
    except CertVerificationError as exc:
        # Keep the batch alive, but don't store the binary
        # garbage the browser got either.
        log.warning("SKIPPED (TLS certificate invalid): %s (%s)", url, exc)
        return None


def _convert_batch_result(cr, url: str, settings, gates, log):
    """Convert one browser result. Returns (WebResult|None, want_pdf)."""
    from hyperresearch.web.safe_http import SafeHTTPError

    if not cr.success:
        return None, False
    try:
        _check_final_url(url, getattr(cr, "redirected_url", None) or cr.url, settings)
    except SafeHTTPError as exc:
        log.warning("dropping batch result for %s: %s", url, exc)
        return None, False
    content = _extract_markdown(cr.markdown)
    metadata = cr.metadata or {}
    converted = _make_web_result(
        cr.url or url,
        metadata,
        content,
        cr.html,
        _extract_media(cr),
        _decode_screenshot(cr.screenshot),
    )
    # Post-fetch binary check — browser may have fetched a PDF inline
    return converted, bool(content and _looks_like_binary(content, gates))


class Crawl4AIProvider:
    name = "crawl4ai"

    def __init__(
        self,
        headless: bool = True,
        user_data_dir: str | None = None,
        profile: str | None = None,
        cookies: list[dict] | None = None,
        magic: bool = False,
        settings: FetchSettings | None = None,
        gates: JunkGates | None = None,
    ):
        # Resolve profile name to path (crawl4ai stores profiles in ~/.crawl4ai/profiles/)
        data_dir = user_data_dir
        if profile and not data_dir:
            data_dir = str(pathlib.Path.home() / ".crawl4ai" / "profiles" / profile)

        self._data_dir = data_dir
        self._headless = headless
        self._cookies = cookies
        self._settings = settings or FetchSettings()
        self._gates = gates or JunkGates()

        browser_kwargs: dict = {"headless": headless}
        if data_dir:
            browser_kwargs["use_managed_browser"] = True
            browser_kwargs["user_data_dir"] = data_dir
        if cookies:
            browser_kwargs["cookies"] = cookies

        self._browser_config = BrowserConfig(**browser_kwargs)

        # Smart wait: initial delay + poll until content stabilizes
        self._wait_js = "js:" + _smart_wait_js(self._settings)
        # Use PruningContentFilter to populate fit_markdown (strips nav/footer chrome)
        self._md_generator = DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(),
        )
        self._run_config = CrawlerRunConfig(
            magic=magic,
            simulate_user=True,
            screenshot=True,
            page_timeout=self._settings.page_timeout_ms,
            wait_for=self._wait_js,
            markdown_generator=self._md_generator,
        )

    def _make_crawler(self) -> AsyncWebCrawler:
        """Build an AsyncWebCrawler wired with the stealth (patchright) adapter.

        crawl4ai's AsyncWebCrawler defaults to PlaywrightAdapter (plain
        playwright); patchright/stealth only engages when an UndetectedAdapter is
        passed via an explicit AsyncPlaywrightCrawlerStrategy. Without this the
        provider's anti-bot behavior is only simulate_user + smart-wait. The
        adapter's use_undetected flag is threaded through every BrowserManager
        launch branch (default, persistent-context, and managed-browser/CDP), so
        this is compatible with the authenticated-profile (user_data_dir) path.
        """
        strategy = AsyncPlaywrightCrawlerStrategy(
            browser_config=self._browser_config,
            browser_adapter=UndetectedAdapter(),
        )
        return AsyncWebCrawler(crawler_strategy=strategy, config=self._browser_config)

    def fetch(self, url: str) -> WebResult:
        # SSRF gate: reject private/loopback/etc. before any browser or http
        # call. PDF redirects are re-checked hop by hop via safe_get; the
        # browser lanes drive their own navigation, so they get the
        # entry-point check here plus a final-URL recheck after the fact
        # (_check_final_url).
        from hyperresearch.web.safe_http import check_url

        check_url(url, self._settings.allow_private_hosts)

        # PDF detection: fetch directly with httpx, extract text with pymupdf
        pdf_failure: str | None = None
        if _is_pdf_url(url):
            result = _fetch_pdf(url, self._settings)
            if result is not None:
                return result
            # Fallback to browser if PDF fetch failed (might be a landing page, not actual PDF)
            pdf_failure = _pdf_failure_reason(url)

        # When visible + profile: use Playwright directly (crawl4ai managed browser ignores headless=False)
        if not self._headless and self._data_dir:
            result = _run_coro(self._fetch_visible(url))
        else:
            result = _run_coro(self._fetch_async(url))

            # Post-fetch PDF detection: if the browser got binary garbage (PDF served
            # inline without proper content-type handling), re-fetch as a direct PDF download.
            if result.content and _looks_like_binary(result.content, self._gates):
                pdf_result = _fetch_pdf(url, self._settings)
                if pdf_result is not None:
                    return pdf_result
                pdf_failure = _pdf_failure_reason(url) or pdf_failure

        # The junk gate downstream only sees "binary garbage"; the reason the
        # PDF lane gave up is what the operator actually needs (#82).
        if pdf_failure:
            result.metadata[PDF_FAILURE_KEY] = pdf_failure
        return result

    async def _fetch_visible(self, url: str) -> WebResult:
        """Fetch using Playwright directly with a visible browser window.

        crawl4ai's managed browser always forces headless. For sites like LinkedIn
        that detect headless mode and kill sessions, we need a truly visible browser.
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=self._data_dir,  # type: ignore[arg-type]
                headless=False,
                viewport={"width": 1280, "height": 900},
                ignore_https_errors=True,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(
                url, wait_until="domcontentloaded", timeout=self._settings.page_timeout_ms
            )

            # Smart wait — same logic (and same builder) as the headless config
            await page.evaluate(_smart_wait_js(self._settings))

            html = await page.content()
            title = await page.title()
            screenshot_bytes = await page.screenshot(type="png")
            final_url = page.url

            await context.close()

        # This lane runs with ignore_https_errors and follows redirects on
        # its own, so where it LANDED needs the same gate as where it started.
        _check_final_url(url, final_url, self._settings)

        # Prefer fit_markdown (main content, no nav/footer chrome) over raw_markdown.
        md_result = self._md_generator.generate_markdown(html, base_url=final_url)
        content = ""
        if md_result and hasattr(md_result, "fit_markdown"):
            content = md_result.fit_markdown or md_result.raw_markdown or ""
        elif md_result and hasattr(md_result, "raw_markdown"):
            content = md_result.raw_markdown or ""
        elif isinstance(md_result, str):
            content = md_result

        return WebResult(
            url=final_url,
            title=title,
            content=content,
            raw_html=html,
            fetched_at=datetime.now(UTC),
            metadata={"title": title},
            screenshot=screenshot_bytes,
        )

    async def _fetch_async(self, url: str) -> WebResult:
        async with self._make_crawler() as crawler:
            result = await crawler.arun(url=url, config=self._run_config)
            # crawl4ai's result.url is the REQUESTED url even after the
            # browser followed redirects; the landing url is redirected_url
            # (hermetic-tier proven — rechecking result.url alone is blind).
            _check_final_url(
                url, getattr(result, "redirected_url", None) or result.url, self._settings
            )
            metadata = result.metadata or {}
            return _make_web_result(
                result.url or url,
                metadata,
                _extract_markdown(result.markdown),
                result.html,
                _extract_media(result),
                _decode_screenshot(result.screenshot),
                _extract_links(result.links or {}),
            )

    def fetch_many(self, urls: list[str]) -> list[WebResult]:
        """Fetch multiple URLs concurrently using crawl4ai's arun_many."""
        return _run_coro(self._fetch_many_async(urls))

    async def _fetch_many_async(self, urls: list[str]) -> list[WebResult]:
        log = logging.getLogger("hyperresearch.web")
        allowed_urls = _gate_batch_urls(urls, self._settings, log)

        # Split: PDFs go direct, rest go through browser
        pdf_urls = [u for u in allowed_urls if _is_pdf_url(u)]
        html_urls = [u for u in allowed_urls if not _is_pdf_url(u)]

        web_results, failed_pdf_urls = _fetch_batch_pdfs(pdf_urls, self._settings, log)
        browser_urls = html_urls + failed_pdf_urls

        if browser_urls:
            async with self._make_crawler() as crawler:
                results = await crawler.arun_many(urls=browser_urls, config=self._run_config)
                for cr, url in zip(results, browser_urls, strict=False):  # type: ignore[arg-type]
                    converted, want_pdf = _convert_batch_result(
                        cr, url, self._settings, self._gates, log
                    )
                    if converted is None:
                        continue
                    if want_pdf:
                        pdf_result = _fetch_binary_pdf(url, self._settings, log)
                        if pdf_result is not None:
                            web_results.append(pdf_result)
                            continue
                    web_results.append(converted)
        return web_results

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError(
            "crawl4ai does not support web search. "
            "Use your agent's built-in search, then pipe URLs into 'hyperresearch fetch'."
        )
