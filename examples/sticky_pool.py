#!/usr/bin/env python3
"""Pin identities to static proxies and stay inside the connection budget.

A static proxy is state. An account that signed in from one IP yesterday
should come from the same IP today, so the mapping from identity to proxy has
to be deterministic and has to survive restarts without a database.

This module uses rendezvous hashing for that:

  * the same identity always lands on the same proxy
  * adding a proxy moves only about 1/N of the identities
  * removing a proxy moves only the identities that lived on it

It also caps concurrent connections per proxy with a semaphore, because a
static proxy has a fixed connection budget (100 per proxy by default here).

    python sticky_pool.py --proxies proxies.csv --assign identities.txt
    python sticky_pool.py --self-test

Standard library only. Requests go out over HTTP proxies.
"""

import argparse
import csv
import hashlib
import sys
import threading
import urllib.request
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Proxy:
    id: str
    host: str
    http_port: int
    username: str = ""
    password: str = ""
    country: str = ""
    isp: str = ""

    @property
    def url(self):
        if self.username:
            return "http://%s:%s@%s:%s" % (self.username, self.password, self.host, self.http_port)
        return "http://%s:%s" % (self.host, self.http_port)


def score(identity, proxy_id):
    """Rendezvous score. The Node port in pool.js computes the same value."""
    return hashlib.sha256(("%s|%s" % (identity, proxy_id)).encode("utf-8")).hexdigest()


class StickyPool:
    def __init__(self, proxies, max_connections=100):
        if not proxies:
            raise ValueError("the pool needs at least one proxy")
        self.proxies = list(proxies)
        self._limits = {p.id: threading.BoundedSemaphore(max_connections) for p in self.proxies}

    def proxy_for(self, identity, country=None):
        """Return the proxy that owns this identity, optionally within one country."""
        candidates = [p for p in self.proxies if country is None or p.country == country]
        if not candidates:
            raise LookupError("no proxy in country %r" % country)
        return max(candidates, key=lambda p: score(identity, p.id))

    def fetch(self, identity, url, timeout=20.0, country=None):
        """GET a URL through the proxy that owns this identity."""
        proxy = self.proxy_for(identity, country)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy.url, "https": proxy.url})
        )
        with self._limits[proxy.id]:
            with opener.open(url, timeout=timeout) as response:
                return proxy, response.status, response.read()


def load_proxies(path):
    """Read the CSV written by inventory.py."""
    proxies = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row.get("http_port"):
                continue
            proxies.append(
                Proxy(
                    id=row["id"],
                    host=row["host"],
                    http_port=int(row["http_port"]),
                    username=row.get("username", ""),
                    password=row.get("password", ""),
                    country=row.get("country", ""),
                    isp=row.get("isp", ""),
                )
            )
    return proxies


def print_assignment(pool, identities):
    load = Counter()
    print("%-28s  %-10s  %-15s  %-7s  %s" % ("identity", "proxy id", "host", "country", "isp"))
    for identity in identities:
        proxy = pool.proxy_for(identity)
        load[proxy.id] += 1
        print("%-28s  %-10s  %-15s  %-7s  %s" % (identity, proxy.id, proxy.host, proxy.country, proxy.isp))
    print()
    for proxy in pool.proxies:
        print("proxy %-10s carries %d identities" % (proxy.id, load[proxy.id]))


def self_test():
    proxies = [Proxy(id=str(n), host="203.0.113.%d" % n, http_port=12345) for n in range(1, 6)]
    identities = ["account-%04d" % n for n in range(1000)]

    before = {i: StickyPool(proxies).proxy_for(i).id for i in identities}
    again = {i: StickyPool(list(reversed(proxies))).proxy_for(i).id for i in identities}
    assert before == again, "mapping must not depend on proxy order or process"

    grown = proxies + [Proxy(id="6", host="203.0.113.6", http_port=12345)]
    after_add = {i: StickyPool(grown).proxy_for(i).id for i in identities}
    moved = [i for i in identities if before[i] != after_add[i]]
    assert all(after_add[i] == "6" for i in moved), "identities may only move to the new proxy"
    assert 100 < len(moved) < 240, "about 1/6 of identities should move, got %d" % len(moved)

    shrunk = [p for p in proxies if p.id != "3"]
    after_remove = {i: StickyPool(shrunk).proxy_for(i).id for i in identities}
    disturbed = [i for i in identities if before[i] != after_remove[i]]
    assert all(before[i] == "3" for i in disturbed), "only identities on the removed proxy may move"

    spread = Counter(before.values())
    assert min(spread.values()) > 150, "load should be roughly even, got %s" % dict(spread)

    print("stable across restarts and proxy order: ok")
    print("adding a sixth proxy moved %d of 1000 identities, all to the new proxy: ok" % len(moved))
    print("removing proxy 3 moved %d identities, all of them its own: ok" % len(disturbed))
    print("spread over 5 proxies: %s" % dict(sorted(spread.items())))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Pin identities to static proxies.")
    parser.add_argument("--proxies", help="CSV written by inventory.py")
    parser.add_argument("--assign", help="text file with one identity per line")
    parser.add_argument("--self-test", action="store_true", help="check the hashing guarantees offline")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(self_test())
    if not (args.proxies and args.assign):
        parser.error("pass --proxies and --assign, or --self-test")

    pool = StickyPool(load_proxies(args.proxies))
    with open(args.assign, encoding="utf-8") as handle:
        identities = [line.strip() for line in handle if line.strip()]
    print_assignment(pool, identities)


if __name__ == "__main__":
    main()
