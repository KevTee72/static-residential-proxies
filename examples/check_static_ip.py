#!/usr/bin/env python3
"""Confirm that a static residential proxy keeps one exit IP.

Sends N requests through the proxy to an IP echo service, then reports every
distinct exit IP it saw, the latency of each request, and a verdict.

    python check_static_ip.py --proxy http://USERNAME:PASSWORD@203.0.113.10:12345
    python check_static_ip.py --proxy http://203.0.113.10:12345 --count 20 --interval 30
    python check_static_ip.py --proxy http://USERNAME:PASSWORD@203.0.113.10:12345 --isp

Exit code 0 means one IP for the whole run. Exit code 1 means the IP changed,
did not match --expect, or every request failed.

Standard library only. The standard library speaks HTTP proxies, not SOCKS5,
so keep the proxy on HTTP for this check.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_ECHO = "https://ipv4.icanhazip.com"
ISP_LOOKUP = "https://ipinfo.io/json"

HINTS = {
    407: "the proxy wants credentials, or your IP is not on the whitelist",
    403: "the proxy refused the request, check the plan status in the dashboard",
    502: "the proxy could not reach the target, try another echo URL",
    503: "the proxy is not ready, a new order can stay PENDING for a short time",
}


def build_opener(proxy_url):
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    opener.addheaders = [("User-Agent", "check-static-ip/1.0")]
    return opener


def fetch_text(opener, url, timeout):
    started = time.monotonic()
    with opener.open(url, timeout=timeout) as response:
        body = response.read(4096).decode("utf-8", "replace").strip()
    return body, time.monotonic() - started


def explain(error):
    if isinstance(error, urllib.error.HTTPError):
        return "HTTP %s: %s" % (error.code, HINTS.get(error.code, error.reason))
    reason = getattr(error, "reason", error)
    text = str(reason)
    if "407" in text:
        return "HTTP 407: " + HINTS[407]
    return text


def run(args):
    opener = build_opener(args.proxy)
    seen = {}
    failures = 0

    for number in range(1, args.count + 1):
        try:
            ip, seconds = fetch_text(opener, args.echo, args.timeout)
            seen.setdefault(ip, []).append(seconds)
            print("%3d  %-15s  %6.0f ms" % (number, ip, seconds * 1000))
        except (urllib.error.URLError, OSError) as error:
            failures += 1
            print("%3d  FAILED           %s" % (number, explain(error)))
        if number < args.count:
            time.sleep(args.interval)

    print()
    if not seen:
        print("VERDICT: no request succeeded, nothing to compare")
        return 1

    for ip, timings in seen.items():
        average = sum(timings) / len(timings) * 1000
        print("%-15s  %d requests  average %.0f ms" % (ip, len(timings), average))
    if failures:
        print("failed requests: %d of %d" % (failures, args.count))

    if args.isp:
        try:
            body, _ = fetch_text(opener, ISP_LOOKUP, args.timeout)
            info = json.loads(body)
            print("network: %s, %s" % (info.get("org", "unknown"), info.get("country", "unknown")))
        except (urllib.error.URLError, OSError, ValueError) as error:
            print("network lookup failed: %s" % explain(error))

    if len(seen) > 1:
        print("VERDICT: the exit IP changed during the run, this is not a static session")
        return 1
    only_ip = next(iter(seen))
    if args.expect and only_ip != args.expect:
        print("VERDICT: static, but %s is not the expected %s" % (only_ip, args.expect))
        return 1
    print("VERDICT: static, one exit IP across %d requests" % sum(len(t) for t in seen.values()))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Confirm a proxy keeps one exit IP.")
    parser.add_argument("--proxy", required=True, help="http://USERNAME:PASSWORD@HOST:PORT, or http://HOST:PORT with IP whitelist auth")
    parser.add_argument("--count", type=int, default=10, help="number of requests (default 10)")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between requests (default 2)")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds per request (default 20)")
    parser.add_argument("--echo", default=DEFAULT_ECHO, help="URL that returns the caller IP as plain text")
    parser.add_argument("--expect", help="the public IP shown in the dashboard, fail if the exit IP differs")
    parser.add_argument("--isp", action="store_true", help="also print the network owner and country of the exit IP")
    sys.exit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
