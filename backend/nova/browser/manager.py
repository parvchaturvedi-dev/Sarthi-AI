"""Persistent browser Nova controls — like a browser it "connects" to once.

Uses Playwright with a persistent profile, so:
  - tabs are REUSED: opening web.whatsapp.com when it's already open just brings
    that tab to the front instead of spawning a new one every time;
  - logins PERSIST across sessions (scan the WhatsApp QR once, stay logged in);
  - later, web tasks can be driven via the DOM (more reliable than OCR).

One browser per process, created lazily on first use and kept alive.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("nova.browser")


def _norm(url: str) -> str:
    return url if "://" in url else "https://" + url


def _domain(url: str) -> str:
    return urlparse(_norm(url)).netloc.replace("www.", "").lower()


class BrowserManager:
    def __init__(self, user_data_dir: str, headless: bool = False, channel: str = "chrome"):
        self.user_data_dir = str(user_data_dir)
        self.headless = headless
        self.channel = channel
        self._pw = None
        self._ctx = None
        self._lock = threading.Lock()

    def _ensure(self):
        if self._ctx is not None:
            return self._ctx
        from playwright.sync_api import sync_playwright

        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        opts = dict(user_data_dir=self.user_data_dir, headless=self.headless,
                    no_viewport=True, args=["--start-maximized"])
        try:                                   # prefer the system Chrome (no download)
            self._ctx = self._pw.chromium.launch_persistent_context(channel=self.channel, **opts)
        except Exception as e:
            log.info("chrome channel unavailable (%s); using bundled chromium", e)
            self._ctx = self._pw.chromium.launch_persistent_context(**opts)
        log.info("browser ready (profile=%s)", self.user_data_dir)
        return self._ctx

    def open_or_focus(self, url: str):
        """Focus an existing tab for this site, or open one if none exists."""
        with self._lock:
            ctx = self._ensure()
            dom = _domain(url)
            blank = None
            for page in ctx.pages:
                try:
                    if dom and dom in page.url:
                        page.bring_to_front()
                        return page
                    if page.url in ("about:blank", "") or page.url.startswith("chrome://newtab"):
                        blank = page
                except Exception:
                    continue
            page = blank or ctx.new_page()      # reuse an empty tab if there is one
            page.goto(_norm(url), wait_until="domcontentloaded")
            page.bring_to_front()
            return page

    def find_tab(self, url_fragment: str):
        """Return an open tab whose URL contains the fragment, else None."""
        if self._ctx is None:
            return None
        frag = url_fragment.lower()
        for page in self._ctx.pages:
            try:
                if frag in page.url.lower():
                    return page
            except Exception:
                continue
        return None

    def close(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = None


# --- process-wide singleton -------------------------------------------------
_BROWSER: "BrowserManager | None" = None


def get_browser(user_data_dir: str = "browser_profile", headless: bool = False) -> BrowserManager:
    global _BROWSER
    if _BROWSER is None:
        _BROWSER = BrowserManager(user_data_dir, headless=headless)
    return _BROWSER
