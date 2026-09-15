import requests

proxies = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050"
}

url = "http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"

try:
    response = requests.get(url, proxies=proxies, timeout=60)
    print("Status:", response.status_code)
    print(response.text[:500])  # Just show first 500 chars
except Exception as e:
    print("Failed:", e)

