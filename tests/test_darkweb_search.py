"""Tests for darkweb_search.py. No Tor and no network: a fake session serves canned pages."""

import io
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import darkweb_search as dws

ONION_A = "http://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.onion/"
ONION_B = "http://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.onion/"

RESULTS_PAGE = f"""
<html><body>
  <li class="result"><a href="/search/redirect?search_term=x&redirect_url={ONION_A}">Site A</a></li>
  <li class="result"><a href="{ONION_B}">Site B</a></li>
  <li class="result"><a href="/search/redirect?search_term=x&redirect_url={ONION_A}">Site A again</a></li>
  <a href="/about/">About Ahmia</a>
  <a href="https://ahmia.fi/documentation/">Docs</a>
  <a href="mailto:someone@example.com">Mail</a>
</body></html>
"""

MATCHING_PAGE = """
<html><body><h1>Boricua news</h1><p>Reports from Puerto  Rico today.</p></body></html>
"""

SCRIPT_ONLY_PAGE = """
<html><head>
  <script>var city = "San Juan"; // puerto rico</script>
  <style>.puerto-rico { color: red; }</style>
</head><body><p>Nothing relevant here.</p></body></html>
"""


class FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url")


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {"User-Agent": "test"}
        self.proxies = {}
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        page = self.pages.get(url)
        if page is None:
            return FakeResponse("missing", status_code=404)
        if isinstance(page, Exception):
            raise page
        return FakeResponse(page)


def quiet():
    """Silence the module logger while a test runs."""
    dws.log.addHandler(logging.NullHandler())
    dws.log.propagate = False


quiet()


class UrlTests(unittest.TestCase):
    def test_spaces_and_specials_are_encoded(self):
        self.assertEqual(dws.search_url("Puerto Rico"),
                         "https://ahmia.fi/search/?q=Puerto+Rico")
        # The old hand-rolled .replace(' ', '+') left these untouched.
        self.assertIn("q=coffee+%26+tea%3F", dws.search_url("coffee & tea?"))

    def test_onion_links_are_recognised_in_both_shapes(self):
        self.assertEqual(dws.onion_from_href(f"/search/redirect?redirect_url={ONION_A}"), ONION_A)
        self.assertEqual(dws.onion_from_href(ONION_B), ONION_B)

    def test_everything_else_is_ignored(self):
        for href in ["/about/", "https://ahmia.fi/docs/", "mailto:a@example.com",
                     "http://example.onion.com/", "javascript:void(0)"]:
            self.assertIsNone(dws.onion_from_href(href), href)

    def test_results_keep_order_and_drop_duplicates(self):
        self.assertEqual(dws.parse_results(RESULTS_PAGE), [ONION_A, ONION_B])


class KeywordTests(unittest.TestCase):
    def test_markup_and_scripts_are_not_searched(self):
        """A keyword that only appears in a script or a class name is a false positive."""
        patterns = dws.compile_keywords([r"puerto\s*rico", r"san\s+juan"])

        self.assertEqual(dws.matching_keywords(dws.visible_text(SCRIPT_ONLY_PAGE), patterns), [])
        # ... and the raw HTML would have matched both, which is the old behaviour.
        self.assertEqual(len(dws.matching_keywords(SCRIPT_ONLY_PAGE, patterns)), 2)

    def test_visible_text_still_matches(self):
        patterns = dws.compile_keywords([r"boricua"])

        self.assertEqual(dws.matching_keywords(dws.visible_text(MATCHING_PAGE), patterns),
                         ["boricua"])

    def test_the_query_itself_is_the_default_keyword(self):
        pattern = dws.compile_keywords([dws.phrase_pattern("Puerto Rico")])[0]

        self.assertTrue(pattern.search("reports from puerto  rico today"))
        self.assertFalse(pattern.search("puertorico"))

    def test_query_text_is_escaped_not_interpreted(self):
        pattern = dws.compile_keywords([dws.phrase_pattern("c++ (beta)")])[0]

        self.assertTrue(pattern.search("Learning C++ (beta) here"))

    def test_a_bad_regex_is_reported_not_raised_as_re_error(self):
        with self.assertRaises(ValueError):
            dws.compile_keywords(["(unclosed"])


class CheckLinkTests(unittest.TestCase):
    def test_a_network_failure_is_not_a_result(self):
        session = FakeSession({ONION_A: requests.ConnectionError("proxy down")})

        result = dws.check_link(session, ONION_A, dws.compile_keywords(["boricua"]))

        self.assertFalse(result.fetched)
        self.assertIn("proxy down", result.error)

    def test_an_error_page_is_not_a_result(self):
        result = dws.check_link(FakeSession({}), ONION_A, dws.compile_keywords(["boricua"]))

        self.assertFalse(result.fetched)
        self.assertEqual(result.error, "HTTP 404")

    def test_a_match_names_the_keyword(self):
        session = FakeSession({ONION_A: MATCHING_PAGE})

        result = dws.check_link(session, ONION_A, dws.compile_keywords(["boricua", "nothing"]))

        self.assertTrue(result.fetched)
        self.assertEqual(result.matches, ["boricua"])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache_path = Path(self.directory.name) / "checked.txt"
        self.output = Path(self.directory.name) / "matches.txt"
        self.patterns = dws.compile_keywords(["boricua"])

    def pages(self, **overrides):
        pages = {dws.search_url("test"): RESULTS_PAGE,
                 ONION_A: MATCHING_PAGE,
                 ONION_B: SCRIPT_ONLY_PAGE}
        pages.update(overrides)
        return pages

    def run_search(self, session, **kwargs):
        cache = dws.Cache(self.cache_path).load()
        slept = []
        matched = dws.run("test", self.patterns, session, cache, self.output,
                          sleep=slept.append, **kwargs)
        return matched, cache, slept

    def test_matches_are_written_and_links_are_cached(self):
        session = FakeSession(self.pages())

        matched, _, slept = self.run_search(session)

        self.assertEqual(matched, [ONION_A])
        self.assertEqual(self.output.read_text(encoding="utf-8").split(), [ONION_A])
        self.assertEqual(self.cache_path.read_text(encoding="utf-8").split(), [ONION_A, ONION_B])
        self.assertEqual(slept, [dws.DEFAULT_DELAY])      # one wait, between the two fetches

    def test_a_link_that_failed_is_not_cached(self):
        """The old version cached every link it tried, so a blip meant never retrying."""
        session = FakeSession(self.pages(**{ONION_B: requests.ConnectionError("timeout")}))

        _, _, _ = self.run_search(session)

        self.assertEqual(self.cache_path.read_text(encoding="utf-8").split(), [ONION_A])

        # Second run, network back: the link that failed is tried again.
        again = FakeSession(self.pages())
        self.run_search(again)
        self.assertIn(ONION_B, again.requested)

    def test_cached_links_are_skipped_on_the_next_run(self):
        self.cache_path.write_text(ONION_A + "\n", encoding="utf-8")
        session = FakeSession(self.pages())

        matched, _, _ = self.run_search(session)

        self.assertEqual(matched, [])
        self.assertNotIn(ONION_A, session.requested)

    def test_a_link_repeated_on_the_page_is_checked_once(self):
        session = FakeSession(self.pages())

        self.run_search(session)

        self.assertEqual(session.requested.count(ONION_A), 1)

    def test_limit_stops_early(self):
        session = FakeSession(self.pages())

        self.run_search(session, limit=1)

        self.assertNotIn(ONION_B, session.requested)

    def test_dry_run_visits_nothing(self):
        session = FakeSession(self.pages())

        matched, _, _ = self.run_search(session, dry_run=True)

        self.assertEqual(matched, [])
        self.assertEqual(session.requested, [dws.search_url("test")])
        self.assertFalse(self.output.exists())


class CommandLineTests(unittest.TestCase):
    def run_main(self, argv, session):
        original = dws.build_session
        dws.build_session = lambda *args, **kwargs: session
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = dws.main(argv)
        finally:
            dws.build_session = original
        return code, out.getvalue(), err.getvalue()

    def test_a_dead_proxy_is_a_message_not_a_traceback(self):
        session = FakeSession({dws.search_url("test"): requests.exceptions.ProxyError("refused")})

        code, _, err = self.run_main(["test", "--dry-run"], session)

        self.assertEqual(code, 1)
        self.assertIn("Tor SOCKS proxy", err)
        self.assertIn("tor_check.py", err)

    def test_a_bad_keyword_regex_exits_two(self):
        code, _, err = self.run_main(["test", "-k", "(unclosed"], FakeSession({}))

        self.assertEqual(code, 2)
        self.assertIn("not a valid regular expression", err)

    def test_output_file_name_follows_the_query(self):
        self.assertEqual(dws.slugify("Puerto Rico!"), "puerto-rico")


if __name__ == "__main__":
    unittest.main(verbosity=2)
