"""Single entry point for creating the Playwright browser."""

from __future__ import annotations

import logging
import os
import weakref


LOGGER = logging.getLogger(__name__)
DEFAULT_CDP_URL = "ws://127.0.0.1:9222"
# Browsers attached over CDP rather than launched by us.
_ATTACHED = weakref.WeakSet()


def get_browser(playwright, **launch_kwargs):
    """Attach to Obscura over CDP, or launch bundled Chromium.

    ``launch_kwargs`` (headless, args, proxy, ...) are launch-only: Obscura is
    already running, so they apply only to the Chromium path. Configure the
    equivalent on the server instead (``obscura serve --proxy ... --stealth``).
    """
    backend = os.environ.get("BROWSER_BACKEND", "obscura").strip().lower()
    if backend != "chromium":
        url = os.environ.get("OBSCURA_CDP_URL", DEFAULT_CDP_URL)
        token = os.environ.get("OBSCURA_CDP_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        try:
            # Must be connect_over_cdp: connect() speaks Playwright's own protocol.
            browser = playwright.chromium.connect_over_cdp(url, headers=headers)
            _ATTACHED.add(browser)
            return browser
        except Exception as error:
            LOGGER.warning(
                "Could not connect to Obscura at %s (%s); falling back to bundled Chromium",
                url,
                str(error).splitlines()[0],
            )
    return playwright.chromium.launch(**launch_kwargs)


def get_context(browser, **context_kwargs):
    """Reuse Obscura's default context; create one on a launched Chromium.

    A freshly launched Chromium has no contexts, so ``context_kwargs`` take
    effect there. Anything Obscura does not support (record_video_dir,
    storage_state, service workers) must stay on that Chromium path.
    """
    if browser.contexts:
        return browser.contexts[0]
    return browser.new_context(**context_kwargs)


def get_request(playwright, context, proxy=None, **request_kwargs):
    """Return the API request client to use alongside ``context``.

    ``context.request`` runs in the Playwright driver, not in the browser. On a
    launched Chromium it inherits the launch proxy and context options. Over
    CDP it inherits neither, so rebuild it with them and the context's cookies;
    otherwise it would bypass the proxy Obscura itself is using.
    """
    if context.browser in _ATTACHED:
        return playwright.request.new_context(
            proxy=proxy,
            storage_state={"cookies": context.cookies(), "origins": []},
            **request_kwargs,
        )
    return context.request
