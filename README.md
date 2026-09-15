# Tor Dark Web Link Checker

A small Python utility that checks onion services through a local Tor SOCKS proxy. `test.py` searches the Ahmia onion search engine for a query, pulls the `.onion` links out of the results page, visits each one over Tor, and records the links whose page content matches a set of keyword regular expressions. `tor_check.py` is a quick connectivity test for the proxy, and `docker-compose.yml` starts the proxy itself. The query and keywords in the code look for Puerto Rico–related content. The link lists the script produces are created at runtime and are not included in the repository.

> **Legal / ethical use.** Onion search results can include illegal or harmful content. Use this only for research you are allowed to do, and follow local law, your organization's policies, and Ahmia's terms. The script only stores URLs, not page content. Do not use it to access, download, or share illegal material.

## How it works

```
docker-compose.yml  ->  dperson/torproxy container  ->  SOCKS5 proxy on port 9050
                                                              |
test.py  (every request goes through socks5h://127.0.0.1:9050)|
                                                              v
  1. GET https://ahmia.fi/search/?q=<query>          (fetched through Tor)
  2. Parse every <a href> with BeautifulSoup, keep the value of the
     redirect_url= query parameter when it contains ".onion"
  3. For each onion link:
        already in checked_links.txt?  -> skip
        GET the onion page (30 s timeout)
        regex-search the page text for the keyword variants
        match  -> append the URL to puertorico_matches.txt
        append the URL to checked_links.txt, then sleep 5 s
  4. Print how many new matches were saved
```

The proxy scheme is `socks5h://`, not `socks5://`. The `h` means hostnames are resolved by the proxy, and `.onion` addresses only work that way because they cannot be resolved by normal DNS.

## Files

### `docker-compose.yml`

Defines a single service, `tor`, using the `dperson/torproxy` image. The container is named `tor-socks`, uses `restart: unless-stopped`, and publishes port `9050` (SOCKS5) on the host. Both Python scripts expect the proxy at `127.0.0.1:9050`.

### `tor_check.py`

A connectivity test for the proxy.

- **How it works:** it builds a `proxies` dict that sends HTTP and HTTPS through `socks5h://127.0.0.1:9050`, then calls `requests.get()` on a hardcoded onion address (a public search engine's onion service) with a 60-second timeout.
- **Inputs:** none. The target URL is set in the `url` variable.
- **Outputs:** prints the HTTP status code and the first 500 characters of the response body, or `Failed: <exception>` if the request fails. If you get a normal status code, Tor routing and onion name resolution are working.

### `test.py`

The link checker itself. The file name is generic, but this is the main script.

- **Configuration (module-level constants):**
  - `query`: the Ahmia search term. It is turned into `ahmia_url`, with spaces replaced by `+`.
  - `keyword_variants`: the regexes to match. They are `puerto[\s\-]?rico`, `puertorrican`, `boricua`, and `san\s+juan`.
  - `CACHE_FILE = "checked_links.txt"`: links that have already been checked.
  - `OUTPUT_FILE = "puertorico_matches.txt"`: links that matched.
- **Functions:**
  - `load_cache()` reads `checked_links.txt` into a set, or returns an empty set if the file doesn't exist.
  - `save_to_cache(link)` appends one URL to `checked_links.txt`.
  - `get_onion_links_from_ahmia()` fetches the Ahmia results page through Tor (60 s timeout) and parses it with BeautifulSoup. For each link containing `redirect_url=`, it pulls that parameter out with `urllib.parse` and keeps it if it contains `.onion`.
  - `check_link_for_keywords(url)` fetches the page through Tor (30 s timeout), lowercases the response text, and returns `True` on the first regex match (`re.IGNORECASE`). If the request fails, it prints the error and returns `False`.
  - `main()` loads the cache and collects the links. For each link it skips cached URLs, checks the rest, appends matches to the output file, caches every link it checked, and sleeps 5 seconds between requests.
- **Inputs:** no command-line arguments. Edit the constants to change the search. It also reads `checked_links.txt` if that file exists.
- **Outputs:** console progress lines prefixed `[*]` (info), `[-]` (skipped), `[+]` (match), and `[!]` (fetch error), plus a final count. Both text files are opened in append mode, so results build up over multiple runs.

## Requirements

- **Python 3.6+.** The code uses f-strings.
- **Python packages:**
  - `requests` with SOCKS support: `requests[socks]`, which installs PySocks. Without it, `socks5h://` proxies fail with a "Missing dependencies for SOCKS support" error.
  - `beautifulsoup4`.
  - `urllib.parse`, `re`, `os`, and `time` are in the standard library.
- **A Tor SOCKS proxy on `127.0.0.1:9050`:** either Docker with Docker Compose (using the included file), or a locally installed Tor daemon, whose default `SocksPort` is 9050.
- **Root / sudo:** not required.

## Usage

```bash
# 1. Start the Tor proxy (Tor needs a short time to bootstrap after the container starts)
docker compose up -d
docker logs tor-socks          # optional: check that bootstrapping finished

# 2. Install the Python dependencies
pip install "requests[socks]" beautifulsoup4

# 3. Confirm onion services are reachable through the proxy
python3 tor_check.py

# 4. Run the checker (writes checked_links.txt and puertorico_matches.txt in the current directory)
python3 test.py
```

To search for something else, edit `query` and `keyword_variants` in `test.py`. The output file name stays whatever `OUTPUT_FILE` is set to. To check every link again from scratch, delete `checked_links.txt`.

## Limitations / notes

- Only the first Ahmia results page is read. There is no pagination.
- Link extraction depends on Ahmia wrapping results in `redirect_url=` links. If Ahmia changes its HTML, the script will find no links.
- The keywords are matched against the raw HTML, including markup and scripts, so you can get false positives. For example, `san\s+juan` also matches many pages that have nothing to do with Puerto Rico.
- Links that fail to load are still added to `checked_links.txt`, so they are never retried unless you delete the cache.
- The cache set is loaded once at startup and isn't updated during the run, so a link that appears twice on the same results page gets checked twice.
- Checks run one at a time, with a 5-second delay and a timeout of up to 30 seconds per link. This is slow on purpose, to go easy on Tor and on the onion services.
- The query is only space-to-`+` encoded before it goes into the URL. Other special characters are not URL-encoded.
- `"9050:9050"` in the Compose file publishes the proxy on all host interfaces. To keep it reachable only from the local machine, bind it as `127.0.0.1:9050:9050`.
- There are no command-line options. All configuration is done by editing constants in the source.

## Author

Jose E. Rodriguez Rios
