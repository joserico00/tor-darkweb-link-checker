"""Search Ahmia for a phrase and report which onion services mention your keywords.

    python darkweb_search.py "Puerto Rico" -k "puerto[\\s-]?rico" -k boricua
    python darkweb_search.py "Puerto Rico" --dry-run        # list the links, visit nothing

Every request goes through the local Tor SOCKS proxy. Links that were fetched
are remembered, so a second run only visits what is new; links that failed are
not remembered, so a proxy hiccup does not blacklist them forever.

Onion search results can include illegal or harmful content. Use this only for
research you are allowed to do, follow local law, your organization's policies
and Ahmia's terms, and do not use it to access or share illegal material. The
script stores URLs only, never page content.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from torproxy import DEFAULT_PROXY, build_session, explain_failure

AHMIA_SEARCH = "https://ahmia.fi/search/"
DEFAULT_CACHE = "checked_links.txt"
DEFAULT_DELAY = 5.0            # seconds between onion fetches, to go easy on the network
DEFAULT_TIMEOUT = 30.0         # onion services are slow
SEARCH_TIMEOUT = 60.0

log = logging.getLogger("darkweb-search")


def search_url(query: str) -> str:
    """The Ahmia URL for a query, with every character properly encoded."""
    return f"{AHMIA_SEARCH}?{urlencode({'q': query})}"


def onion_from_href(href: str) -> str | None:
    """The onion URL a results-page link points at, or None if it is not one."""
    target = href
    if "redirect_url=" in href:
        # Ahmia wraps each result in /search/redirect?redirect_url=<target>
        target = parse_qs(urlparse(href).query).get("redirect_url", [""])[0]

    parts = urlparse(target)
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.hostname or not parts.hostname.endswith(".onion"):
        return None
    return target


def parse_results(html: str) -> list[str]:
    """Every onion link on a results page, in order, without duplicates."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = onion_from_href(anchor["href"])
        if url and url not in seen:
            seen.add(url)
            links.append(url)
    return links


def visible_text(html: str) -> str:
    """Page text with markup, scripts and styles removed.

    Searching the raw HTML matches class names, URLs and script contents, which
    is where most of this tool's false positives used to come from.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def compile_keywords(patterns: list[str]) -> list[re.Pattern]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as error:
            raise ValueError(f"{pattern!r} is not a valid regular expression: {error}") from error
    return compiled


def phrase_pattern(query: str) -> str:
    """A regex for the query itself, tolerant of the spacing between its words."""
    return r"\s+".join(re.escape(word) for word in query.split())


def matching_keywords(text: str, patterns: list[re.Pattern]) -> list[str]:
    return [pattern.pattern for pattern in patterns if pattern.search(text)]


@dataclass
class Cache:
    """URLs already fetched, on disk and in memory.

    Only successfully fetched links go in. A link that timed out stays out, so
    the next run tries it again instead of skipping it forever.
    """

    path: Path | None
    seen: set[str] = field(default_factory=set)

    def load(self) -> "Cache":
        if self.path and self.path.exists():
            self.seen = {line.strip() for line in
                         self.path.read_text(encoding="utf-8").splitlines() if line.strip()}
        return self

    def __contains__(self, url: str) -> bool:
        return url in self.seen

    def add(self, url: str) -> None:
        if url in self.seen:
            return
        self.seen.add(url)          # also guards duplicates within a single run
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(url + "\n")


@dataclass
class Check:
    url: str
    fetched: bool
    matches: list[str] = field(default_factory=list)
    error: str = ""


def check_link(session, url: str, patterns: list[re.Pattern],
               timeout: float = DEFAULT_TIMEOUT) -> Check:
    """Fetch one onion page and report which keywords its visible text contains."""
    try:
        response = session.get(url, timeout=timeout)
    except requests.RequestException as error:
        return Check(url, fetched=False, error=str(error))

    if response.status_code >= 400:
        return Check(url, fetched=False, error=f"HTTP {response.status_code}")

    return Check(url, fetched=True, matches=matching_keywords(visible_text(response.text), patterns))


def slugify(query: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return slug or "search"


def run(query: str, patterns: list[re.Pattern], session, cache: Cache,
        output: Path | None, delay: float = DEFAULT_DELAY,
        timeout: float = DEFAULT_TIMEOUT, limit: int | None = None,
        dry_run: bool = False, sleep=time.sleep) -> list[str]:
    """Search, then visit each new onion link. Returns the URLs that matched."""
    log.info("Searching Ahmia for %r ...", query)
    response = session.get(search_url(query), timeout=SEARCH_TIMEOUT)
    response.raise_for_status()

    links = parse_results(response.text)
    log.info("Found %d onion link(s) on the results page.", len(links))

    if dry_run:
        for url in links:
            log.info("  %s", url)
        return []

    matched: list[str] = []
    checked = 0
    for url in links:
        if url in cache:
            log.debug("Skipping (already checked): %s", url)
            continue
        if limit is not None and checked >= limit:
            log.info("Stopping at the --limit of %d link(s).", limit)
            break
        if checked:
            sleep(delay)

        checked += 1
        log.info("Checking: %s", url)
        result = check_link(session, url, patterns, timeout)

        if not result.fetched:
            # Not cached: a failure here is usually the network, not the site.
            log.warning("Could not fetch %s: %s", url, result.error)
            continue

        cache.add(url)
        if result.matches:
            log.info("MATCH (%s): %s", ", ".join(result.matches), url)
            matched.append(url)
            if output:
                with output.open("a", encoding="utf-8") as handle:
                    handle.write(url + "\n")

    log.info("Done. Checked %d new link(s); %d matched.", checked, len(matched))
    if matched and output:
        log.info("Matches appended to %s", output)
    return matched


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Ahmia and report onion services whose text matches your keywords.",
        epilog="Research use only: follow local law, your organization's policies and Ahmia's terms.",
    )
    parser.add_argument("query", help="what to search Ahmia for")
    parser.add_argument("-k", "--keyword", action="append", default=[], metavar="REGEX",
                        help="regex a page must match (repeatable; default: the query itself)")
    parser.add_argument("-o", "--output", help="file for matching URLs (default: matches_<query>.txt)")
    parser.add_argument("-c", "--cache", default=DEFAULT_CACHE,
                        help=f"file of already-checked URLs (default: {DEFAULT_CACHE})")
    parser.add_argument("--no-cache", action="store_true", help="check every link, remember nothing")
    parser.add_argument("--proxy", default=DEFAULT_PROXY,
                        help=f"Tor SOCKS proxy (default: {DEFAULT_PROXY})")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"seconds between onion fetches (default: {DEFAULT_DELAY})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"seconds to wait for each onion page (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--limit", type=int, help="check at most this many new links")
    parser.add_argument("--dry-run", action="store_true",
                        help="list the links the search returns without visiting any of them")
    parser.add_argument("-v", "--verbose", action="store_true", help="show skipped links too")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(message)s", stream=sys.stdout)

    try:
        patterns = compile_keywords(args.keyword or [phrase_pattern(args.query)])
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    cache = Cache(None if args.no_cache else Path(args.cache)).load()
    output = None if args.dry_run else Path(args.output or f"matches_{slugify(args.query)}.txt")
    session = build_session(args.proxy)

    try:
        run(args.query, patterns, session, cache, output,
            delay=args.delay, timeout=args.timeout, limit=args.limit, dry_run=args.dry_run)
    except requests.RequestException as error:
        print(f"error: {explain_failure(error, args.proxy)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
