"""HTTP transport for the VDH inspections portal.

The portal sits behind an AWS WAF that answers 403 to datacenter traffic —
GitHub Actions runners, cloud functions and public fetch proxies all get turned
away, while an ordinary home/office connection is served normally. So the
transport supports two modes:

  direct   — used when the bot runs somewhere with a residential-style IP
             (a laptop, a home server, a Raspberry Pi).
  proxied  — set INSPECTIONS_PROXY_TEMPLATE to a URL containing "{url}" and
             every request is routed through it. Any fetch-a-page-for-me
             service works, e.g.
                 https://api.scraperapi.com/?api_key=KEY&url={url}
                 https://app.scrapingbee.com/api/v1/?api_key=KEY&url={url}
             A plain forward proxy works too: set HTTPS_PROXY instead.

`FetchBlocked` is raised on a WAF rejection so callers can report the real
cause instead of a silent empty digest.
"""

import gzip
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": os.environ.get("INSPECTIONS_USER_AGENT", DEFAULT_UA),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class FetchBlocked(RuntimeError):
    """The portal refused the request (WAF/IP block) rather than 404'ing."""


class FetchError(RuntimeError):
    """The request failed for a reason other than a block."""


def _proxied(url: str) -> str:
    template = os.environ.get("INSPECTIONS_PROXY_TEMPLATE", "").strip()
    if not template:
        return url
    if "{url}" not in template:
        raise FetchError("INSPECTIONS_PROXY_TEMPLATE must contain '{url}'")
    return template.replace("{url}", urllib.parse.quote(url, safe=""))


def fetch(url: str, *, timeout: int = 30, retries: int = 3, extra_headers: dict | None = None) -> str:
    """GET `url` and return the decoded body.

    Raises FetchBlocked on 403 (the signature of the portal's WAF) and
    FetchError on anything else that survives the retries.
    """
    headers = dict(BROWSER_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    last_error: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(_proxied(url), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise FetchBlocked(
                    f"403 from {urllib.parse.urlsplit(url).netloc} — the portal's WAF "
                    f"rejects this network. Run the bot from a residential connection "
                    f"or set INSPECTIONS_PROXY_TEMPLATE."
                ) from e
            if e.code == 404:
                raise FetchError(f"404 for {url}") from e
            last_error = e
        except Exception as e:  # timeouts, DNS, connection resets
            last_error = e

        if attempt < retries - 1:
            # Backoff with jitter — the portal is a small public service.
            time.sleep(2 ** attempt + random.uniform(0, 0.5))

    raise FetchError(f"GET {url} failed after {retries} attempts: {last_error}")
