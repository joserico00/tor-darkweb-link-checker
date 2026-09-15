import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import os
import re

proxies = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050"
}

query = "Puerto Rico"
ahmia_url = f"https://ahmia.fi/search/?q={query.replace(' ', '+')}"
keyword_variants = [
    r"puerto[\s\-]?rico",
    r"puertorrican",
    r"boricua",
    r"san\s+juan"
]

CACHE_FILE = "checked_links.txt"
OUTPUT_FILE = "puertorico_matches.txt"

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_to_cache(link):
    with open(CACHE_FILE, "a") as f:
        f.write(link + "\n")

def get_onion_links_from_ahmia():
    print("[*] Searching Ahmia...")
    response = requests.get(ahmia_url, proxies=proxies, timeout=60)
    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "redirect_url=" in href:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            real_url = qs.get("redirect_url", [None])[0]
            if real_url and ".onion" in real_url:
                links.append(real_url)
    return links

def check_link_for_keywords(url):
    try:
        print(f"[*] Checking: {url}")
        response = requests.get(url, proxies=proxies, timeout=30)
        content = response.text.lower()
        for pattern in keyword_variants:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False
    except Exception as e:
        print(f"[!] Failed to fetch {url}: {e}")
        return False

def main():
    cache = load_cache()
    onion_links = get_onion_links_from_ahmia()
    print(f"[*] Found {len(onion_links)} links from Ahmia.")
    
    matches = []

    for link in onion_links:
        if link in cache:
            print(f"[-] Skipping (cached): {link}")
            continue
        if check_link_for_keywords(link):
            print(f"[+] MATCH: {link}")
            matches.append(link)
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                f.write(link + "\n")
        save_to_cache(link)
        time.sleep(5)  # Respect Tor and onion services

    print(f"\n✅ Done. {len(matches)} new matching links saved to {OUTPUT_FILE}.")

if __name__ == "__main__":
    main()

