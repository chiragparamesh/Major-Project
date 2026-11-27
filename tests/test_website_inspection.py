"""Deep website inspection (Safety Center): parked/ad-redirect pages, SSRF guard, scoring. No real network."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import website_trust as wt
from app import create_app
from db import db

PARKED_PAGE = """<html><head><title>chirag.com</title></head><body>
<h1>This domain is for sale</h1><p>Make an offer.</p>
<iframe src="https://ads.parkingnet.example/frame"></iframe>
<script src="https://cdn.parkingnet.example/a.js"></script>
<script>var ua = navigator.userAgent; /* decide where to send the visitor */</script></body></html>"""
CLEAN_PAGE = "<html><head><title>My Shop</title></head><body><h1>Welcome</h1><a href='/about'>About</a></body></html>"


def _resp(status=200, body="", location=None, encoding="utf-8"):
    r = MagicMock()
    r.status_code = status
    r.headers = {"Location": location} if location else {}
    r.encoding = encoding
    r.raw.read.return_value = body.encode()
    return r


@pytest.fixture
def app():
    a = create_app(start_bot=False)
    a.config["TESTING"] = True
    with a.app_context():
        db.create_all()
        yield a
        db.session.remove()
        db.drop_all()


def _checker():
    return wt.WebsiteTrustScore()


def test_parked_page_with_third_party_ad_code_is_flagged():
    with patch.object(wt, "_host_class", return_value="public"), \
         patch.object(wt.requests, "get", return_value=_resp(body=PARKED_PAGE)):
        insp = _checker()._inspect_site("chirag.com")
    assert insp["fetched"] and insp["parked"] and insp["ua_sniff"] and insp["has_iframe"]
    assert "parkingnet.example" in insp["external_hosts"]
    pts, reasons = _checker()._score_inspection(insp, "chirag.com")
    assert pts >= 55 and any("parked" in r for r in reasons) and any("another" in r or "other websites" in r for r in reasons)


def test_clean_site_gets_no_inspection_penalty():
    with patch.object(wt, "_host_class", return_value="public"), \
         patch.object(wt.requests, "get", return_value=_resp(body=CLEAN_PAGE)):
        insp = _checker()._inspect_site("myshop.in")
    pts, reasons = _checker()._score_inspection(insp, "myshop.in")
    assert pts == 0 and reasons == []


def test_http_redirect_chain_to_another_site_is_detected():
    chain = [_resp(302, location="http://tracker.example.net/a"), _resp(302, location="http://offers.example.org/b"),
             _resp(200, body="<html><title>Meet singles near you</title><body>dating singles chat</body></html>")]
    with patch.object(wt, "_host_class", return_value="public"), patch.object(wt.requests, "get", side_effect=chain):
        insp = _checker()._inspect_site("shortlink.in")
    assert insp["hops"] == 2 and insp["redirect_other"] == "offers.example.org"
    pts, reasons = _checker()._score_inspection(insp, "shortlink.in")
    assert pts >= 15 + 25 + 35 and any("adult, dating" in r for r in reasons)


def test_script_redirect_to_other_domain_is_detected():
    page = "<html><body><script>window.location = 'http://sketchy.example.net/go';</script></body></html>"
    with patch.object(wt, "_host_class", return_value="public"), patch.object(wt.requests, "get", return_value=_resp(body=page)):
        insp = _checker()._inspect_site("legit-looking.in")
    assert insp["script_redirect"] == "sketchy.example.net"


def test_private_addresses_are_never_fetched():
    """SSRF guard: the checker must not be usable to probe the laptop/LAN."""
    with patch.object(wt, "_host_class", return_value="private"), patch.object(wt.requests, "get") as get:
        insp = _checker()._inspect_site("127.0.0.1.nip.io")
    get.assert_not_called()
    assert not insp["fetched"] and insp["error"] == "private-address"
    pts, reasons = _checker()._score_inspection(insp, "127.0.0.1.nip.io")
    assert pts >= 40 and any("private" in r for r in reasons)


def test_redirect_into_a_private_address_is_blocked_mid_chain():
    classes = iter(["public", "private"])
    with patch.object(wt, "_host_class", side_effect=lambda h: next(classes)), \
         patch.object(wt.requests, "get", return_value=_resp(302, location="http://192.168.0.1/admin")) as get:
        insp = _checker()._inspect_site("evil-redirect.in")
    assert get.call_count == 1  # the private target was never requested
    assert not insp["fetched"] and insp["error"] == "private-address"


def test_https_failure_falls_back_to_http():
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url.startswith("https"):
            raise wt.requests.exceptions.SSLError("bad cert")
        return _resp(body=CLEAN_PAGE)
    with patch.object(wt, "_host_class", return_value="public"), patch.object(wt.requests, "get", side_effect=fake_get):
        insp = _checker()._inspect_site("nocert.in")
    assert insp["fetched"] and insp["ssl_error"] and calls[0].startswith("https") and calls[1].startswith("http://")


def test_deep_check_rates_a_parked_domain_not_safe(app):
    c = _checker()
    parked = {"fetched": True, "parked": True, "hops": 0, "redirect_other": None, "script_redirect": None,
              "adult_terms": [], "external_hosts": ["parkingnet.example"], "has_iframe": True, "ua_sniff": True}
    with patch.object(c, "_resolves", return_value=True), patch.object(c, "_check_ssl", return_value=False), \
         patch.object(c, "_get_domain_age", return_value=-1), patch.object(c, "_check_google_safe_browsing", return_value=False), \
         patch.object(c, "_check_openphish", return_value=False), patch.object(c, "_inspect_site", return_value=parked):
        score, verdict, reasons = c.check("chirag.com", deep=True)
    assert verdict in ("SUSPICIOUS", "FRAUD") and score >= 60


def test_deep_check_bypasses_a_stale_safe_cache(app):
    """A domain cached as SAFE earlier must be re-inspected when the user checks it in the Safety Center."""
    from database import WebsiteReputation
    from datetime import datetime
    db.session.add(WebsiteReputation(domain="chirag.com", trust_score=0, is_scam=False, ssl_valid=True,
                                     domain_age_days=-1, google_safe=True, openphish_flagged=False,
                                     last_checked=datetime.utcnow()))
    db.session.commit()
    c = _checker()
    parked = {"fetched": True, "parked": True, "hops": 0, "adult_terms": [], "external_hosts": ["x.example"],
              "has_iframe": True, "ua_sniff": True}
    with patch.object(c, "_resolves", return_value=True), patch.object(c, "_check_ssl", return_value=True), \
         patch.object(c, "_get_domain_age", return_value=-1), patch.object(c, "_check_google_safe_browsing", return_value=False), \
         patch.object(c, "_check_openphish", return_value=False), patch.object(c, "_inspect_site", return_value=parked):
        assert c.check("chirag.com")[1] == "SAFE"                    # fast path trusts the cache (payments)
        assert c.check("chirag.com", deep=True)[1] != "SAFE"         # Safety Center re-inspects


def test_unrelated_short_domain_is_not_a_lookalike():
    c = _checker()
    assert wt.levenshtein_distance("example.com", "apple.com") == 3   # the old rule (<=3) flagged this
    # and the real check no longer reports it
    with patch.object(c, "_resolves", return_value=True), patch.object(c, "_check_ssl", return_value=True), \
         patch.object(c, "_get_domain_age", return_value=-1), patch.object(c, "_check_google_safe_browsing", return_value=False), \
         patch.object(c, "_check_openphish", return_value=False), patch.object(c, "_inspect_site", return_value={"fetched": False}):
        a = create_app(start_bot=False)
        with a.app_context():
            db.create_all()
            _, verdict, reasons = c.check("example.com", deep=True)
            db.session.remove()
            db.drop_all()
    assert not any("Typosquatting" in r for r in reasons)
