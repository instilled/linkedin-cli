"""Browser management and session persistence using Patchright.

Patchright patches Playwright to avoid bot detection (WebDriver flag,
navigator.plugins, etc.).  On top of that we configure a realistic
Chrome-on-macOS fingerprint: user-agent, viewport, locale, timezone,
color scheme, and Chromium launch args.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

CONFIG_DIR = Path.home() / ".config" / "linkedin-cli"
SESSION_FILE = CONFIG_DIR / "session.json"

# Realistic Chrome 131 / macOS user-agent
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Extra Chromium flags that make the browser look more human
_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


def _context_opts(*, extra: dict | None = None) -> dict:
    """Return kwargs for browser.new_context() with realistic fingerprint."""
    opts: dict = {
        "user_agent": _UA,
        "viewport": {"width": 1440, "height": 900},
        "screen": {"width": 1440, "height": 900},
        "device_scale_factor": 2,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "color_scheme": "light",
        "has_touch": False,
        "is_mobile": False,
        "java_script_enabled": True,
        "bypass_csp": False,
        "extra_http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        },
    }
    if extra:
        opts.update(extra)
    return opts


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)


def ensure_browser():
    """Install Chromium if not already present."""
    # Patchright stores browsers in the same place as Playwright
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache.exists():
        cache = Path.home() / ".cache" / "ms-playwright"

    # Check if any chromium directory exists
    has_chromium = any(
        d.name.startswith("chromium-") for d in cache.iterdir()
    ) if cache.exists() else False

    if not has_chromium:
        print("Installing Chromium browser (first run only)…")
        subprocess.run(
            [sys.executable, "-m", "patchright", "install", "chromium"],
            check=True,
        )


def has_session() -> bool:
    return SESSION_FILE.exists()


def clear_session():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def login():
    """Open browser for interactive LinkedIn login. Saves session cookies."""
    ensure_config_dir()
    ensure_browser()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=_CHROME_ARGS)
        context = browser.new_context(**_context_opts())
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        # Wait for user to complete login — they land on /feed/
        try:
            page.wait_for_url("**/feed/**", timeout=300_000)
        except Exception:
            if "/feed" not in page.url and "/in/" not in page.url:
                browser.close()
                raise RuntimeError("Login timed out or failed.")

        # Save browser state (cookies + localStorage)
        state = context.storage_state()
        SESSION_FILE.write_text(json.dumps(state, indent=2))
        os.chmod(SESSION_FILE, 0o600)
        browser.close()


def relogin():
    """Re-authenticate after session expiry. Opens a headed browser."""
    print("Session expired — opening browser to re-authenticate…")
    login()


def create_page(playwright):
    """Create a headless browser page with saved session. Returns (browser, page)."""
    if not has_session():
        raise RuntimeError("Not logged in. Run 'linkedin login' first.")
    ensure_browser()

    state = json.loads(SESSION_FILE.read_text())
    browser = playwright.chromium.launch(headless=True, args=_CHROME_ARGS)
    context = browser.new_context(**_context_opts(extra={"storage_state": state}))
    page = context.new_page()
    return browser, page


def is_logged_in(page) -> bool:
    """Check if current page indicates an active session."""
    url = page.url
    return "/login" not in url and "/authwall" not in url
