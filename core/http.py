"""
core/http.py — one resilient HTTP helper for the whole bot.

Replaces the repo-wide pattern of `requests.get(url).json()` with no status
check, no retry, and a bare `except` that hides rate-limits. Everything here:
  • sets a sane timeout
  • retries with exponential backoff
  • treats HTTP 429 as retryable (free APIs rate-limit constantly)
  • returns a caller-supplied default instead of raising, so one flaky feed
    never crashes a cycle — but logs at DEBUG so failures aren't invisible.
"""
import time
import logging
import requests

log = logging.getLogger("http")
DEFAULT_HEADERS = {"User-Agent": "BR0THER-H00D/1.0 (+https://h00d.fun)"}


def _request(method, url, *, params=None, json=None, headers=None,
             timeout=8, retries=2, backoff=0.6, default=None):
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, params=params, json=json,
                                  headers=hdrs, timeout=timeout)
            if r.status_code == 429:                 # rate limited -> back off
                raise requests.HTTPError("429 Too Many Requests")
            r.raise_for_status()
            return r.json()
        except Exception as e:                        # noqa: BLE001 - intentional boundary
            last = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))  # 0.6s, 1.2s, 2.4s ...
    log.debug("%s %s failed after %d tries: %s", method, url, retries + 1, last)
    return default


def get_json(url, *, params=None, headers=None, timeout=8, retries=2,
             backoff=0.6, default=None):
    """GET and parse JSON. Returns `default` (None) on any failure."""
    return _request("GET", url, params=params, headers=headers,
                    timeout=timeout, retries=retries, backoff=backoff, default=default)


def post_json(url, *, json=None, headers=None, timeout=12, retries=1,
              backoff=0.6, default=None):
    """POST and parse JSON. Returns `default` (None) on any failure."""
    return _request("POST", url, json=json, headers=headers,
                    timeout=timeout, retries=retries, backoff=backoff, default=default)
