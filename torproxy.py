"""Shared Tor SOCKS proxy setup for the scripts in this repository.

The scheme is ``socks5h``, not ``socks5``: the ``h`` makes the proxy resolve
hostnames, which is the only way ``.onion`` addresses work, since no ordinary
DNS server can resolve them.
"""

from __future__ import annotations

import requests

DEFAULT_PROXY = "socks5h://127.0.0.1:9050"

# Tor Browser's string would be a lie coming from a script, and the library
# default advertises the exact requests/urllib3 versions in use.
USER_AGENT = "tor-darkweb-link-checker/1.0"

SOCKS_HELP = (
    "SOCKS support is missing. Install it with:  pip install \"requests[socks]\"\n"
    "(that pulls in PySocks, which requests needs for socks5h:// proxies)"
)

PROXY_HELP = (
    "Could not reach the Tor SOCKS proxy at {proxy}.\n"
    "Start it with `docker compose up -d --wait`, or run a local Tor daemon, "
    "then confirm it works with `python tor_check.py`."
)


def build_session(proxy: str = DEFAULT_PROXY, user_agent: str = USER_AGENT) -> requests.Session:
    """A session whose HTTP and HTTPS traffic both go through the Tor proxy."""
    session = requests.Session()
    session.proxies = {"http": proxy, "https": proxy}
    session.headers["User-Agent"] = user_agent
    return session


def explain_failure(error: Exception, proxy: str = DEFAULT_PROXY) -> str:
    """Turn a requests exception into a line that says what to do about it."""
    text = str(error)
    if "SOCKS" in text and "Missing dependencies" in text:
        return SOCKS_HELP
    if isinstance(error, requests.exceptions.ProxyError) or "Connection refused" in text:
        return PROXY_HELP.format(proxy=proxy)
    return text
