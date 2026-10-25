#!/usr/bin/env python3
"""Check a redirect map after a site migration.

Reads lines of `old URL -> expected new URL` (or a bare URL to just trace it),
follows every redirect hop itself, and writes one CSV row per line with the
chain, the final URL and plain issue codes.

    python3 redirect_map_check.py map.txt > report.csv
    python3 redirect_map_check.py map.txt --workers 20 --user-agent googlebot

Standard library only (Python 3.8+). No browser: JavaScript redirects are not
followed; a <meta http-equiv="refresh"> is reported as META_REFRESH.
"""
import argparse
import concurrent.futures
import csv
import http.client
import re
import ssl
import sys
from urllib.parse import urljoin, urlsplit

UA = {
    "browser": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "googlebot": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36 "
                 "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}
TEMPORARY = {302, 303, 307}
META_RE = re.compile(rb'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*content=["\']?\s*\d+\s*;\s*url=([^"\'>\s]+)', re.I)


def parse_line(line):
    """'old -> new' → (old, new); 'url' → (url, None). Blank/comment → None."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "->" in line:
        old, new = (p.strip() for p in line.split("->", 1))
        return old, new or None
    return line, None


def normalise(url):
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    return url


def same_url(a, b, ignore_slash=True):
    if a is None or b is None:
        return False
    a, b = a.strip(), b.strip()
    if ignore_slash:
        a, b = a.rstrip("/"), b.rstrip("/")
    return a.lower() == b.lower()


def request(url, ua, timeout):
    """One GET without following redirects → (status, location, first 64 KB of body)."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise ValueError("invalid URL")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(host, parts.port, timeout=timeout,
                                           context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(host, parts.port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"User-Agent": ua, "Accept": "*/*"})
        resp = conn.getresponse()
        body = resp.read(65536) if resp.status not in REDIRECT_CODES else b""
        return resp.status, resp.getheader("Location"), body
    finally:
        conn.close()


def trace(old, expected, ua, timeout, max_hops):
    url, hops, seen, issues = normalise(old), [], set(), []
    final_status = None
    for _ in range(max_hops + 1):
        if url in seen:
            issues.append("REDIRECT_LOOP")
            break
        seen.add(url)
        try:
            status, location, body = request(url, ua, timeout)
        except Exception as e:  # DNS, timeout, TLS, refused…
            hops.append((url, "ERR"))
            issues.append("UNREACHABLE: " + type(e).__name__)
            break
        hops.append((url, status))
        final_status = status
        nxt = None
        if status in REDIRECT_CODES and location:
            nxt = urljoin(url, location)
            if status in TEMPORARY:
                issues.append("TEMPORARY_REDIRECT")
        else:
            m = META_RE.search(body or b"")
            if m:
                nxt = urljoin(url, m.group(1).decode("utf-8", "replace"))
                issues.append("META_REFRESH")
        if not nxt:
            break
        if url.startswith("https://") and nxt.startswith("http://"):
            issues.append("HTTPS_TO_HTTP")
        url = nxt
    else:
        issues.append("TOO_MANY_REDIRECTS")
    final = hops[-1][0] if hops else normalise(old)
    redirects = len(hops) - 1
    if redirects > 1:
        issues.append("REDIRECT_CHAIN")
    if isinstance(final_status, int) and final_status >= 400 and hops[-1][1] != "ERR":
        issues.append(f"FINAL_{final_status // 100}XX")
    if redirects >= 1 and urlsplit(final).path in ("", "/") and urlsplit(normalise(old)).path not in ("", "/"):
        issues.append("REDIRECT_TO_HOMEPAGE")
    match = ""
    if expected:
        match = "yes" if same_url(final, expected) else "no"
        if match == "no":
            issues.append("EXPECTED_MISMATCH")
    return {
        "input": old,
        "expected": expected or "",
        "final_url": final,
        "final_status": final_status if final_status is not None else "",
        "redirects": max(redirects, 0),
        "chain": " -> ".join(str(c) for _, c in hops),
        "matches_expected": match,
        "issues": ", ".join(dict.fromkeys(issues)),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", help="text file: one 'old -> new' pair or URL per line ('-' = stdin)")
    ap.add_argument("--workers", type=int, default=10, help="parallel requests (default 10)")
    ap.add_argument("--timeout", type=float, default=15, help="seconds per hop (default 15)")
    ap.add_argument("--max-hops", type=int, default=10, help="redirects to follow (default 10)")
    ap.add_argument("--user-agent", choices=sorted(UA), default="browser")
    args = ap.parse_args()
    src = sys.stdin if args.file == "-" else open(args.file, encoding="utf-8")
    pairs = [p for p in (parse_line(l) for l in src) if p]
    ua = UA[args.user_agent]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda p: trace(p[0], p[1], ua, args.timeout, args.max_hops), pairs))
    w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]) if rows else ["input"])
    w.writeheader()
    w.writerows(rows)
    bad = sum(1 for r in rows if r["issues"])
    print(f"{len(rows)} lines checked, {bad} with issues", file=sys.stderr)


if __name__ == "__main__":
    main()
