# Tor Dark Web Link Checker

A small Python utility that searches the [Ahmia](https://ahmia.fi) onion search engine for a phrase, visits each `.onion` result through a local Tor SOCKS proxy, and records the ones whose page text matches your keywords. `tor_check.py` verifies the proxy before you start, and `docker-compose.yml` runs the proxy itself. The link lists are written at run time and are not part of the repository.

```bash
python darkweb_search.py "Puerto Rico" -k "puerto[\s-]?rico" -k boricua -k "san\s+juan"
python darkweb_search.py "Puerto Rico" --dry-run       # list what the search returns, visit nothing
```

> **Legal / ethical use.** Onion search results can include illegal or harmful content. Use this only for research you are allowed to do, and follow local law, your organization's policies, and Ahmia's terms. The script stores URLs only, never page content. Do not use it to access, download, or share illegal material.

## How it works

```
docker compose up -d --wait  ->  Tor container  ->  SOCKS5 proxy on 127.0.0.1:9050
                                                            |
darkweb_search.py (every request goes through socks5h://127.0.0.1:9050)
                                                            v
  1. GET https://ahmia.fi/search/?q=<query>        (query URL-encoded in full)
  2. Collect the .onion URLs from the results page, in order, without duplicates
  3. For each new link:
        already in checked_links.txt?  -> skip
        GET the onion page (30 s timeout)
        strip scripts, styles and markup, then regex-search the visible text
        match    -> append the URL to matches_<query>.txt
        fetched  -> remember it in checked_links.txt
        failed   -> leave it out, so the next run tries again
        wait --delay seconds before the next fetch
  4. Report how many links were checked and how many matched
```

The proxy scheme is `socks5h://`, not `socks5://`. The `h` means the proxy resolves hostnames, and `.onion` addresses only work that way because ordinary DNS cannot resolve them.

## Files

| File | Description |
|---|---|
| `darkweb_search.py` | The link checker and its command line |
| `tor_check.py` | Confirms traffic leaves through Tor and that onion addresses resolve |
| `torproxy.py` | Shared proxy settings and the "here is what to do" error messages |
| `Dockerfile`, `torrc` | A minimal Tor SOCKS proxy built from the official Alpine image |
| `docker-compose.yml` | Runs that proxy, published on `127.0.0.1:9050` only |
| `tests/test_darkweb_search.py` | 21 tests, all offline — a fake session serves canned pages |

## Options

| Option | Default | What it does |
|---|---|---|
| `query` | required | What to search Ahmia for |
| `-k`, `--keyword` | the query itself | Regex a page must match; repeat for several |
| `-o`, `--output` | `matches_<query>.txt` | Where matching URLs are appended |
| `-c`, `--cache` | `checked_links.txt` | Links already visited |
| `--no-cache` | off | Check every link and remember nothing |
| `--proxy` | `socks5h://127.0.0.1:9050` | Tor SOCKS proxy |
| `--delay` | `5.0` | Seconds between onion fetches |
| `--timeout` | `30.0` | Seconds to wait for each onion page |
| `--limit` | none | Check at most this many new links |
| `--dry-run` | off | List the search results without visiting any of them |
| `-v`, `--verbose` | off | Also log the links skipped as already checked |

Keywords are regular expressions, matched case-insensitively. With none given, the query itself is used as a phrase, tolerant of the spacing between its words.

## Requirements

- **Python 3.9+**
- `requests[socks]` (PySocks) and `beautifulsoup4`: `pip install -r requirements.txt`
- **A Tor SOCKS proxy on `127.0.0.1:9050`**, either the included container or a local Tor daemon (whose default `SocksPort` is 9050). Root is not required.

## Usage

```bash
# 1. Start the proxy. --wait returns once Tor has finished bootstrapping.
docker compose up -d --wait

# 2. Install the Python dependencies
pip install -r requirements.txt

# 3. Confirm Tor is usable (exit status 0 means both checks passed)
python tor_check.py

# 4. Search. Writes checked_links.txt and matches_<query>.txt in the current directory.
python darkweb_search.py "Puerto Rico" -k "puerto[\s-]?rico" -k boricua
```

To check every link again from scratch, delete `checked_links.txt` or pass `--no-cache`.

## Tests

```bash
python tests/test_darkweb_search.py      # or: python -m unittest discover tests
```

The tests need neither Tor nor a network: a fake session serves canned pages, which also covers the failure paths — a refused proxy, a dead onion service, a page whose only keyword is inside a `<script>`.

## Notes and limitations

- Only the first Ahmia results page is read; there is no pagination.
- Link extraction handles both shapes Ahmia uses (a `redirect_url=` wrapper and a direct link). If Ahmia changes its HTML in some third way, the search will find nothing.
- Keywords are matched against the page's **visible text**, with scripts, styles and markup removed, so class names and URLs no longer cause false positives. A broad pattern can still match text that is not about your subject.
- Checks run one at a time, with a delay between them and a timeout per link. This is slow on purpose, to go easy on Tor and on the onion services.
- The container publishes the proxy on `127.0.0.1:9050`, so it is reachable from this machine only, and Tor inside it accepts connections from Docker's private networks only.

## Author

Jose E. Rodriguez Rios
