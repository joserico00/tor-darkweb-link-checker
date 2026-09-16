"""Confirm the local Tor SOCKS proxy works before starting a longer job.

    python tor_check.py                 # routing + onion name resolution
    python tor_check.py --skip-onion    # routing only, when onion services are slow

Exit status is 0 only if every check passed, so this can gate a script or a
CI step.
"""

from __future__ import annotations

import argparse
import sys

import requests

from torproxy import DEFAULT_PROXY, build_session, explain_failure

# Returns {"IsTor": true, "IP": "..."} when the request really came out of Tor.
TOR_CHECK_API = "https://check.torproject.org/api/ip"

# A well-known, long-lived onion service, used only to prove that .onion
# addresses resolve through the proxy.
DEFAULT_ONION = "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"

DEFAULT_TIMEOUT = 60.0


def check_routing(session, timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Is traffic actually leaving through Tor?"""
    try:
        response = session.get(TOR_CHECK_API, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        return False, explain_failure(error)
    except ValueError:
        return False, f"{TOR_CHECK_API} did not return JSON"

    if payload.get("IsTor"):
        return True, f"traffic is leaving through Tor (exit IP {payload.get('IP', 'unknown')})"
    return False, ("the proxy answered, but the request did not come out of the Tor network "
                   f"(IP {payload.get('IP', 'unknown')})")


def check_onion(session, url: str = DEFAULT_ONION, timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Can the proxy resolve and reach a .onion address?"""
    try:
        response = session.get(url, timeout=timeout)
    except requests.RequestException as error:
        return False, explain_failure(error)
    return True, f"reached {url} (HTTP {response.status_code})"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check that the Tor SOCKS proxy is usable.")
    parser.add_argument("--proxy", default=DEFAULT_PROXY,
                        help=f"Tor SOCKS proxy (default: {DEFAULT_PROXY})")
    parser.add_argument("--onion", default=DEFAULT_ONION, help="onion address to test against")
    parser.add_argument("--skip-onion", action="store_true", help="only check that routing works")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"seconds to wait for each response (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args(argv)

    session = build_session(args.proxy)
    checks = [("Tor routing", lambda: check_routing(session, args.timeout))]
    if not args.skip_onion:
        checks.append(("Onion resolution", lambda: check_onion(session, args.onion, args.timeout)))

    failed = 0
    for label, check in checks:
        ok, detail = check()
        print(f"[{'ok' if ok else 'FAIL'}] {label}: {detail}")
        failed += not ok

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
