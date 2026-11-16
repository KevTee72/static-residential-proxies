#!/usr/bin/env python3
"""Export active static residential proxies from the Proxy-Cheap API to CSV.

Calls GET https://api.proxy-cheap.com/proxies, keeps the entries whose
networkType is RESIDENTIAL_STATIC and whose status is ACTIVE, and writes the
CSV that sticky_pool.py and pool.js read. It also lists proxies that expire
soon, so a pinned identity does not lose its IP by surprise.

    export PROXY_CHEAP_API_KEY=...
    export PROXY_CHEAP_API_SECRET=...
    python inventory.py --out proxies.csv --expiring 7

    python inventory.py --from-file proxies.sample.json --out proxies.csv

Create the key and secret at https://app.proxy-cheap.com/api-keys.
The CSV holds proxy passwords. Keep it out of version control.

Standard library only.
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = "https://api.proxy-cheap.com/proxies"
FIELDS = ["id", "host", "public_ip", "http_port", "socks5_port", "protocol",
          "username", "password", "country", "isp", "expires_at"]


def fetch_proxies():
    key = os.environ.get("PROXY_CHEAP_API_KEY")
    secret = os.environ.get("PROXY_CHEAP_API_SECRET")
    if not (key and secret):
        sys.exit("Set PROXY_CHEAP_API_KEY and PROXY_CHEAP_API_SECRET, or pass --from-file.")
    request = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/json", "X-Api-Key": key, "X-Api-Secret": secret},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        sys.exit("API returned HTTP %s. Check the key, the secret and the account." % error.code)


def to_row(item):
    connection = item.get("connection") or {}
    auth = item.get("authentication") or {}
    return {
        "id": item.get("id"),
        "host": connection.get("connectIp") or connection.get("publicIp"),
        "public_ip": connection.get("publicIp"),
        "http_port": connection.get("httpPort") or "",
        "socks5_port": connection.get("socks5Port") or "",
        "protocol": item.get("proxyType", ""),
        "username": auth.get("username") or "",
        "password": auth.get("password") or "",
        "country": item.get("countryCode", ""),
        "isp": (item.get("metadata") or {}).get("ispName", ""),
        "expires_at": item.get("expiresAt", ""),
    }


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description="Export static residential proxies to CSV.")
    parser.add_argument("--out", default="proxies.csv", help="CSV path (default proxies.csv)")
    parser.add_argument("--expiring", type=int, default=7, help="warn about proxies that expire within N days")
    parser.add_argument("--from-file", help="read a saved API response instead of calling the API")
    args = parser.parse_args()

    if args.from_file:
        with open(args.from_file, encoding="utf-8") as handle:
            items = json.load(handle)
    else:
        items = fetch_proxies()

    static = [i for i in items if i.get("networkType") == "RESIDENTIAL_STATIC"]
    active = [to_row(i) for i in static if i.get("status") == "ACTIVE"]

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(active)

    print("%d proxies on the account, %d static residential, %d active" % (len(items), len(static), len(active)))
    print("wrote %s" % args.out)

    waiting = [i for i in static if i.get("status") != "ACTIVE"]
    for item in waiting:
        print("skipped %s with status %s" % (item.get("id"), item.get("status")))

    cutoff = datetime.now(timezone.utc) + timedelta(days=args.expiring)
    for row in active:
        expires = parse_time(row["expires_at"])
        if expires and expires <= cutoff:
            print("expires soon: proxy %s (%s, %s) on %s" % (row["id"], row["public_ip"], row["isp"], expires.date()))


if __name__ == "__main__":
    main()
