"""Single HTTP entrypoint for every adapter.

Several sources sit behind Cloudflare and reject Python's default User-Agent outright,
so every request goes out with a browser-style UA.
"""

import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def get(url: str, timeout: int = 90, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()
