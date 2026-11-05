import re
import socket
import ssl
import logging
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime
from config import Config
from env_loader import env_str, is_placeholder

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 6 * 3600        # reputation results reused for 6 hours
EXTERNAL_TIMEOUT = 3.0              # per external call
CHECK_BUDGET_SECONDS = 3.5          # whole network part of one check(), run in parallel
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="wts")
_openphish_cache = {"at": 0.0, "feed": set()}
_openphish_lock = threading.Lock()
# Last outcome per external service for /api/health/otp (never contains keys).
EXTERNAL_STATUS = {"safe_browsing": {"state": "not called"}, "openphish": {"state": "not called"}}


def _note(service: str, state: str):
    EXTERNAL_STATUS[service] = {"state": state, "at": datetime.utcnow().isoformat(timespec="seconds") + "Z"}

# Levenshtein distance helper
def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
        
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
        
    return previous_row[-1]

class WebsiteTrustScore:
    WHITELIST = [
        'paytm.com', 'phonepe.com', 'googlepay.com',
        'bhimupi.org.in', 'npci.org.in', 'sbi.co.in',
        'hdfcbank.com', 'icicibank.com', 'axisbank.com',
        'yesbank.in', 'kotak.com', 'paytmbank.com',
        'amazon.com', 'amazon.in', 'google.com', 'google.co.in', 'flipkart.com', 'paypal.com',
        'myntra.com', 'swiggy.com', 'zomato.com', 'irctc.co.in', 'netflix.com', 'facebook.com',
        'instagram.com', 'whatsapp.com', 'microsoft.com', 'apple.com', 'airtel.in', 'jio.com'
    ]

    # Brand names scam sites imitate (look-alike / brand-in-name checks, label only, no TLD).
    BRAND_LABELS = ['amazon', 'flipkart', 'google', 'paypal', 'myntra', 'swiggy', 'zomato', 'irctc',
                    'netflix', 'facebook', 'instagram', 'whatsapp', 'microsoft', 'hdfcbank', 'icicibank',
                    'axisbank', 'paytm', 'phonepe', 'airtel']

    _HOST_RE = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}")

    @staticmethod
    def normalize_domain(raw) -> str:
        """'https://www.Example.com:443/path?x' -> 'example.com'. Returns '' if it is not a hostname."""
        d = str(raw or "").strip().lower()
        d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)
        d = re.split(r"[/?#]", d, maxsplit=1)[0].rsplit("@", 1)[-1].split(":")[0].strip(".")
        if d.startswith("www."):
            d = d[4:]
        return d if WebsiteTrustScore._HOST_RE.fullmatch(d) else ""

    def _resolves(self, domain: str):
        """True/False = the name does/does not exist; None = lookup itself failed (neutral)."""
        try:
            socket.getaddrinfo(domain, 443)
            return True
        except socket.gaierror as e:
            # EAI_NONAME / NODATA = no such site; anything else = resolver trouble.
            return False if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)) else None
        except OSError:
            return None

    def _check_ssl(self, domain: str):
        """True = valid cert, False = bad/missing cert, None = unknown (network/DNS issue: neutral)."""
        context = ssl.create_default_context()
        try:
            with socket.create_connection((domain, 443), timeout=EXTERNAL_TIMEOUT) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as ssock:
                    ssock.getpeercert()
                    return True
        except (ssl.SSLError, ssl.CertificateError) as e:
            logger.warning(f"SSL check: invalid certificate for {domain} ({type(e).__name__})")
            return False
        except ConnectionRefusedError:
            return False  # nothing listening on 443
        except OSError as e:
            logger.warning(f"SSL check inconclusive for {domain} ({type(e).__name__})")
            return None

    def _get_domain_age(self, domain: str) -> int:
        """Looks up domain age in days using WHOIS. Fallback to -1 on failure"""
        try:
            import whois
            w = whois.whois(domain)  # runs in the bounded pool; check() never waits past its budget
            creation_date = w.creation_date
            
            # If multiple dates returned, take the first one
            if isinstance(creation_date, list):
                creation_date = creation_date[0]
                
            if creation_date:
                age = (datetime.now() - creation_date).days
                return max(0, age)
        except Exception as e:
            logger.warning(f"WHOIS check failed for {domain} ({type(e).__name__})")
            
        # Standard fallback: simulate older domain if WHOIS fails to avoid false alerts, 
        # or return a default code like -1. We use -1 to signify 'unknown'.
        return -1

    def _check_google_safe_browsing(self, domain: str) -> bool:
        """Checks domain against Google Safe Browsing API"""
        key = env_str("GOOGLE_SAFE_BROWSING_API_KEY") or str(Config.GOOGLE_SAFE_BROWSING_API_KEY or "")
        if is_placeholder(key):
            # Simulation logic: mark domains containing 'scam', 'double', or 'paytm-refund' as unsafe
            malicious_keywords = ['scam', 'double', 'paytm-refund', 'free-cash']
            return any(kw in domain.lower() for kw in malicious_keywords)
            
        # Key goes in params, never in a logged URL / exception message.
        url = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
        payload = {
            "client": {"clientId": "mlbfd-system", "clientVersion": "1.0.0"},
            "threatInfo": {
                "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": f"http://{domain}/"}, {"url": f"https://{domain}/"}]
            }
        }
        try:
            r = requests.post(url, params={"key": key}, json=payload, timeout=EXTERNAL_TIMEOUT)
            if r.status_code == 200:
                _note("safe_browsing", "ok")
                return "matches" in r.json()
            # 400 bad key, 403 API disabled / key restricted, 429 quota: neutral, never block.
            _note("safe_browsing", f"HTTP{r.status_code}")
            logger.warning(f"Google Safe Browsing returned HTTP {r.status_code}; treating as neutral")
        except (requests.exceptions.RequestException, ValueError) as e:
            _note("safe_browsing", type(e).__name__)
            logger.warning(f"Google Safe Browsing call failed ({type(e).__name__}); treating as neutral")
        return False

    def _check_openphish(self, domain: str) -> bool:
        """Checks domain against OpenPhish database feed"""
        key = Config.OPENPHISH_API_KEY
        if not key or key == "MOCK":
            # Simulation logic
            malicious_keywords = ['phish', 'verify-upi', 'bank-update-login']
            return any(kw in domain.lower() for kw in malicious_keywords)
            
        # Community free feed or API request
        # Free community feed, downloaded at most once per CACHE_TTL_SECONDS.
        with _openphish_lock:
            fresh = time.time() - _openphish_cache["at"] < CACHE_TTL_SECONDS
        if not fresh:
            try:
                r = requests.get("https://openphish.com/feed.txt", timeout=EXTERNAL_TIMEOUT,
                                 headers={"User-Agent": "MLBFD/1.0 (academic fraud-detection demo)"})
                if r.status_code == 200:
                    feed = set()
                    for line in r.text.splitlines():
                        host = line.strip().lower().split("//", 1)[-1].split("/", 1)[0]
                        if host:
                            feed.add(host)
                    with _openphish_lock:
                        _openphish_cache.update(at=time.time(), feed=feed)
                    _note("openphish", "ok")
                else:
                    _note("openphish", f"HTTP{r.status_code}")
            except requests.exceptions.RequestException as e:
                _note("openphish", type(e).__name__)
                logger.warning(f"OpenPhish feed download failed ({type(e).__name__}); treating as neutral")
        with _openphish_lock:
            return domain.lower() in _openphish_cache["feed"]

    def check(self, domain: str) -> tuple:
        """
        Evaluate WTS across 5 checks:
        - Check 1: Typosquatting (Levenshtein <= 3) -> 40 pts
        - Check 2: SSL Handshake failure -> 25 pts
        - Check 3: Domain age via WHOIS (<30 days -> 20 pts, <7 days -> 40 pts)
        - Check 4: Google Safe Browsing API match -> 50 pts
        - Check 5: OpenPhish flagged -> 50 pts
        Returns: (score (0-100), verdict (SAFE/CAUTION/SUSPICIOUS/FRAUD), reasons (list))
        """
        original = str(domain or "").strip()
        domain = self.normalize_domain(original)
        if not domain:
            # Free text such as a person's name is not a website: never report it as safe.
            shown = original[:40] or "(empty)"
            return 0, "INVALID", [f"'{shown}' is not a valid website address (example: example.com)"]
            
        # Suffix/Bank provider whitelist check
        bank_suffixes = ['okaxis', 'okhdfc', 'okicici', 'paytm', 'ybl', 'axl', 'ibl', 'sbi', 'barodampay', 'okgoogle', 'oksbi', 'okhdfcbank']
        provider_name = domain.split('.')[0] if '.' in domain else domain
        
        if domain in self.WHITELIST or provider_name in bank_suffixes:
            return 0, "TRUSTED", []
            
        # Database cache layer
        from db import db
        from database import WebsiteReputation
        
        cached = None
        try:
            cached = WebsiteReputation.query.filter_by(domain=domain).first()
            if cached:
                # Check if evaluated in last 24 hours
                age = datetime.utcnow() - cached.last_checked
                if age.total_seconds() < CACHE_TTL_SECONDS:
                    # Reconstruct reasons based on cached fields for the flags
                    cached_reasons = []
                    score = float(cached.trust_score)
                    if cached.is_scam:
                        cached_reasons.append("Flagged by scam reputation records")
                    if not cached.ssl_valid:
                        cached_reasons.append("Invalid or missing SSL certificate")
                    if cached.domain_age_days != -1 and cached.domain_age_days < 7:
                        cached_reasons.append(f"Domain is very new (age: {cached.domain_age_days} days)")
                    elif cached.domain_age_days != -1 and cached.domain_age_days < 30:
                        cached_reasons.append(f"Domain is relatively new (age: {cached.domain_age_days} days)")
                    if not cached.google_safe:
                        cached_reasons.append("Flagged by Google Safe Browsing as unsafe")
                    if cached.openphish_flagged:
                        cached_reasons.append("Flagged by OpenPhish database feed")
                        
                    # Determine verdict
                    if score >= 80:
                        verdict = "FRAUD"
                    elif score >= 60:
                        verdict = "SUSPICIOUS"
                    elif score >= 40:
                        verdict = "CAUTION"
                    else:
                        verdict = "SAFE"
                        
                    logger.info(f"WTS Cache hit for domain '{domain}': score={score}, verdict={verdict}")
                    return score, verdict, cached_reasons
        except Exception as e:
            logger.error(f"Error checking WebsiteReputation cache: {e}")
            
        score = 0
        reasons = []
        
        # Check 1: Typosquatting
        typosquatted = False
        for trusted in self.WHITELIST:
            dist = levenshtein_distance(domain, trusted)
            if 0 < dist <= 3:
                score += 40
                typosquatted = True
                reasons.append(f"Typosquatting attempt detected (similar to {trusted})")
                break
                
        # Checks 2-5 hit the network: run them in parallel under one budget so a slow
        # WHOIS/DNS/API can never stall a payment. Unfinished checks are neutral.
        futures = {
            "dns": _pool.submit(self._resolves, domain),
            "ssl": _pool.submit(self._check_ssl, domain),
            "age": _pool.submit(self._get_domain_age, domain),
            "sb": _pool.submit(self._check_google_safe_browsing, domain),
            "op": _pool.submit(self._check_openphish, domain),
        }
        neutral = {"dns": None, "ssl": None, "age": -1, "sb": False, "op": False}
        deadline = time.monotonic() + CHECK_BUDGET_SECONDS
        results = {}
        for name, fut in futures.items():
            try:
                results[name] = fut.result(timeout=max(0.0, deadline - time.monotonic()))
            except FuturesTimeout:
                logger.warning(f"website check '{name}' exceeded {CHECK_BUDGET_SECONDS}s budget for {domain}; neutral")
                results[name] = neutral[name]
            except Exception as e:
                logger.warning(f"website check '{name}' failed ({type(e).__name__}); neutral")
                results[name] = neutral[name]

        # Look-alike / brand-in-name (amazon -> awazon, amazon-login.com)
        label = domain.split(".")[-2] if domain.count(".") >= 1 else domain
        if not typosquatted:
            for brand in self.BRAND_LABELS:
                dist = levenshtein_distance(label, brand)
                if label != brand and len(label) >= 5 and (
                        dist == 1 or (dist == 2 and len(brand) >= 7) or (brand in label and len(brand) >= 5)):
                    score += 40
                    typosquatted = True
                    reasons.append(f"Look-alike of the well-known brand '{brand}' (possible impersonation)")
                    break

        # A website that does not exist cannot be called safe.
        if results["dns"] is False:
            score += 40
            reasons.append("This website address does not exist (it cannot be found on the internet)")

        # Check 2: SSL Validation (None = inconclusive network result: no penalty)
        ssl_valid = results["ssl"] is not False
        if not ssl_valid:
            score += 25
            reasons.append("Invalid or missing SSL certificate")

        # Check 3: Domain Age
        age = results["age"]
        if age != -1:
            if age < 7:
                score += 40
                reasons.append(f"Domain is very new (age: {age} days)")
            elif age < 30:
                score += 20
                reasons.append(f"Domain is relatively new (age: {age} days)")
        else:
            # If WHOIS failed, we don't penalize unless it's typosquatted
            pass
            
        # Check 4: Google Safe Browsing
        google_safe = not results["sb"]
        if not google_safe:
            score += 50
            reasons.append("Flagged by Google Safe Browsing as unsafe")
            
        # Check 5: OpenPhish
        openphish_flagged = results["op"]
        if openphish_flagged:
            score += 50
            reasons.append("Flagged by OpenPhish database feed")
            
        final_score = min(score, 100)
        
        # Determine verdict
        if final_score >= 80:
            verdict = "FRAUD"
        elif final_score >= 60:
            verdict = "SUSPICIOUS"
        elif final_score >= 40:
            verdict = "CAUTION"
        else:
            verdict = "SAFE"
            
        # Save or update cache in database
        try:
            if not cached:
                new_cache = WebsiteReputation(
                    domain=domain,
                    is_scam=(final_score >= 80.0),
                    trust_score=final_score,
                    ssl_valid=ssl_valid,
                    domain_age_days=age,
                    google_safe=google_safe,
                    openphish_flagged=openphish_flagged,
                    last_checked=datetime.utcnow()
                )
                db.session.add(new_cache)
            else:
                cached.is_scam = (final_score >= 80.0)
                cached.trust_score = final_score
                cached.ssl_valid = ssl_valid
                cached.domain_age_days = age
                cached.google_safe = google_safe
                cached.openphish_flagged = openphish_flagged
                cached.last_checked = datetime.utcnow()
            db.session.commit()
            logger.info(f"Saved WTS Cache for domain '{domain}': score={final_score}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error saving/updating WebsiteReputation cache: {e}")
            
        return final_score, verdict, reasons
