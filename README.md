# Static Residential Proxies

<p align="center">
  <a href="https://www.proxy-cheap.com/">
  </a>
</p>

Client code written for a rotating gateway treats an IP as disposable: one hostname, a fresh address per request, retry until something works. [Static residential proxies](https://www.proxy-cheap.com/services/static-residential-proxies) are the opposite case. You rent a short list of fixed addresses, each one keeps its IP for the whole rental term, and that turns every address into state your code has to manage. Which account lives on which IP, how many connections each IP is carrying, and when each one expires all become your problem.

Most write ups stop at the definition. This repo covers the engineering that follows from it, with scripts in [examples/](examples/) that verify an IP is really static, pin identities to IPs without a database, and export your inventory from the provider API. Proxy-Cheap is the reference provider because its API returns everything the scripts need. The hashing and verification code works with any provider that hands you a host, a port and credentials.

## Table of contents

- [What are static residential proxies](#what-are-static-residential-proxies)
- [The numbers that shape your code](#the-numbers-that-shape-your-code)
- [Quick start](#quick-start)
- [Verify that the IP is static](#verify-that-the-ip-is-static)
- [Pin each identity to one IP](#pin-each-identity-to-one-ip)
- [Stay inside the connection budget](#stay-inside-the-connection-budget)
- [Manage static residential proxy servers through the API](#manage-static-residential-proxy-servers-through-the-api)
- [Password or IP whitelist](#password-or-ip-whitelist)
- [SOCKS5 and DNS](#socks5-and-dns)
- [Static or rotating: decide by session shape](#static-or-rotating-decide-by-session-shape)
- [Before you buy a static residential proxy](#before-you-buy-a-static-residential-proxy)
- [FAQ](#faq)

---

## What are static residential proxies

A static residential proxy is a proxy server with a fixed IP address that an internet service provider has registered as its own. Two properties define it:

| Property | What it means | Why your code cares |
|---|---|---|
| ISP assigned | The address belongs to a consumer ISP network, not to a cloud host | Sites that score IP reputation read it as an ordinary subscriber line |
| Static | The same IP answers for the whole rental term | Sessions, cookies and sign in history stay tied to one address |

The servers themselves sit in datacenters, which is why the same product is also sold as [ISP proxies](https://www.proxy-cheap.com/services/isp-proxies). You get the address of a home connection with the uptime and speed of hosted hardware.

The contrast with rotating residential traffic is what matters in practice. A rotating gateway picks a new exit IP per request or per short session. A static proxy never picks. Whatever you send to `203.0.113.10:12345` today leaves from the same public IP next week.

## The numbers that shape your code

These come from the Proxy-Cheap product page and support docs, read on 16 November 2026. Check the live page before you size anything, because plan limits change.

| | Basic | Dedicated and Premium |
|---|---|---|
| Users per IP | Shared by up to 3 | 1 |
| Bandwidth | 1 GB per month | Unlimited |
| Speed | No upgrades | 100 Mbit/s by default, up to 1 Gbit/s with an upgrade |
| Concurrent connections | No concurrency upgrades | Up to 100 per proxy |
| Protocols | HTTP and SOCKS5 | HTTP and SOCKS5 |
| Targeting | Country and ISP | Country and ISP |

Three of these become constants in your code. The connection ceiling becomes a semaphore size. The 1 GB cap on Basic means a byte counter if you scrape with it. Basic shares each IP between up to 3 users, which suits stateless, low volume work. Anything tied to an account belongs on a plan with one user per IP.

Rental terms on the page are 7 days, 1 month and 12 months, billed per IP. The 7 day term is the cheap way to test a target before you commit an identity to an address.

## Quick start

Every static proxy has four values on its details page: IP, port, username and password. Test them from a terminal first.

```bash
curl -x http://203.0.113.10:12345 -U "USERNAME:PASSWORD" https://ipv4.icanhazip.com
```

The response should be the public IP shown in the dashboard. Run it three times. If the answer changes between runs, you are not on a static product.

[examples/curl_examples.sh](examples/curl_examples.sh) wraps this with a repeat check, a timing breakdown and the SOCKS5 variants.

## Verify that the IP is static

One curl call proves the proxy works. It does not prove the IP holds. [examples/check_static_ip.py](examples/check_static_ip.py) sends a series of requests, records every distinct exit IP, and exits non zero if it sees more than one.

```bash
python examples/check_static_ip.py \
  --proxy http://USERNAME:PASSWORD@203.0.113.10:12345 \
  --count 20 --interval 30 --expect 203.0.113.10 --isp
```

```text
  1  203.0.113.10        212 ms
  2  203.0.113.10        198 ms
...
203.0.113.10     20 requests  average 204 ms
network: AS64500 Example ISP, US
VERDICT: static, one exit IP across 20 requests
```

`--expect` fails the run when the exit IP differs from the one you were sold. `--isp` prints the network owner of the exit IP, which is how you confirm the address sits on the ISP you selected at checkout. Put the script in CI or a cron job and the exit code tells you when an address stops behaving.

## Pin each identity to one IP

This is the part that rotating proxy code never needs. If account A signed in from one IP yesterday and a different one today, the platform sees a location change and asks for verification. So the rule is one identity, one IP, permanently.

A lookup table in a database does the job, and it adds a dependency every worker has to reach. [examples/sticky_pool.py](examples/sticky_pool.py) gets the same result with rendezvous hashing: hash the identity together with each proxy id, and the highest score wins.

```python
from sticky_pool import StickyPool, load_proxies

pool = StickyPool(load_proxies("proxies.csv"), max_connections=100)

proxy = pool.proxy_for("account-0001")
proxy, status, body = pool.fetch("account-0001", "https://ipv4.icanhazip.com")
```

Any worker on any machine computes the same answer from the same proxy list, with no shared state. What makes it worth using over `hash(identity) % len(proxies)` is how it behaves when the list changes:

| Event | Modulo hashing | Rendezvous hashing |
|---|---|---|
| Add a sixth proxy to five | About 83% of identities move | About 17% move, all to the new proxy |
| Remove one proxy | About 80% of identities move | Only the identities on that proxy move |

The self test measures this on 1,000 identities:

```bash
python examples/sticky_pool.py --self-test
```

```text
stable across restarts and proxy order: ok
adding a sixth proxy moved 174 of 1000 identities, all to the new proxy: ok
removing proxy 3 moved 199 identities, all of them its own: ok
spread over 5 proxies: {'1': 206, '2': 189, '3': 199, '4': 207, '5': 199}
```

[examples/pool.js](examples/pool.js) is a Node port that produces the identical mapping, so mixed Python and Node workers agree on where every identity lives. Its self test checks its output against the Python values.

One caveat. If an account must never move, even when you grow the pool, write its assignment to storage once and treat the hash as the default for new identities only.

## Stay inside the connection budget

A rotating gateway absorbs whatever concurrency you throw at it. A static proxy has a ceiling, and Proxy-Cheap documents it as up to 100 concurrent connections per proxy in its [thread limit article](https://support.proxy-cheap.com/hc/en-us/articles/24651225742237-How-many-concurrent-sessions-threads-can-be-used). Past the ceiling, connections drop or fail, and those failures look like target errors in your logs.

`StickyPool` holds one bounded semaphore per proxy, so request number 101 waits for a free slot. Two things eat the budget faster than people expect:

- **Headless browsers.** One page load opens many connections at once. Ten browser tabs can use the budget that 100 plain HTTP workers would.
- **Idle keep alive connections.** A connection pool that holds sockets open counts against the ceiling while doing nothing. Cap the pool size in your HTTP client at the same number as the semaphore.

If one IP is not enough, add IPs and let the hash spread the identities. More addresses also spreads reputation risk, which a bigger thread allowance on a single address does not.

## Manage static residential proxy servers through the API

Copying IPs out of a dashboard works for three proxies and falls apart at thirty. The [Proxy-Cheap API](https://docs.proxy-cheap.com/) authenticates with two headers, `X-Api-Key` and `X-Api-Secret`, and one call lists everything you hold:

```bash
curl -s https://api.proxy-cheap.com/proxies \
  -H "Accept: application/json" \
  -H "X-Api-Key: $PROXY_CHEAP_API_KEY" \
  -H "X-Api-Secret: $PROXY_CHEAP_API_SECRET"
```

Static residential entries carry `"networkType": "RESIDENTIAL_STATIC"`. The fields that matter:

| Field | Use |
|---|---|
| `connection.connectIp`, `connection.httpPort`, `connection.socks5Port` | Where your client connects |
| `connection.publicIp` | The exit IP, the value to pass to `--expect` |
| `authentication.username`, `authentication.password` | Credentials |
| `authentication.whitelistedIps` | Source IPs allowed in without a password |
| `metadata.ispName`, `countryCode` | What you targeted at checkout |
| `status`, `expiresAt` | Whether the proxy is usable and for how long |

[examples/inventory.py](examples/inventory.py) turns that response into the CSV the pool scripts read, skips anything that is not `ACTIVE`, and warns about proxies close to expiry:

```bash
python examples/inventory.py --out proxies.csv --expiring 7
```

```text
3 proxies on the account, 3 static residential, 2 active
wrote proxies.csv
skipped 100003 with status PENDING
expires soon: proxy 100001 (203.0.113.10, EXAMPLE ISP A) on 2026-12-01
```

Expiry is the failure that hurts most with pinned identities. When a rental lapses, every account on that IP loses its address at once. Two API calls prevent it: `POST /proxies/{id}/extend-period` renews one proxy, and `POST /proxies/{id}/auto-extend/enable` makes renewal automatic. The API also sends webhooks, including `proxy.status.changed` and `proxy.maintenance_window.created`, so a worker can pause the affected identities instead of failing through a maintenance window.

To try the export without an account, run it against the bundled sample: `python examples/inventory.py --from-file examples/proxies.sample.json`.

## Password or IP whitelist

Static residential proxies accept either method, and you can switch per proxy in the dashboard or with `POST /proxies/{id}/change-authentication-type`.

| | Username and password | IP whitelist |
|---|---|---|
| Works from | Anywhere | Only the source IPs you registered |
| Secret in your code | Yes | No |
| Fits | Laptops, CI runners, anything with a changing address | Servers with a fixed outbound IP |
| Catch | Credentials end up in env files and logs | Changes are limited to once every 30 minutes |

The 30 minute limit is the detail to design around. Autoscaled workers that come up on new addresses cannot register themselves fast enough, so give that fleet a NAT gateway with one outbound IP or keep it on password auth. `POST /proxies/{id}/whitelist-ip` takes the full list as `{"ips": ["198.51.100.7"]}`.

## SOCKS5 and DNS

Each proxy speaks one protocol at a time. Most proxies ship set to HTTP, and you switch to SOCKS5 in the dashboard or with `POST /proxies/{id}/change-protocol` and a body of `{"newType": "SOCKS5"}`. The port changes when the protocol does, so pull a fresh inventory afterwards.

With SOCKS5, pick where hostnames get resolved:

```bash
curl -x socks5://203.0.113.10:12345  -U "USERNAME:PASSWORD" https://ipv4.icanhazip.com
curl -x socks5h://203.0.113.10:12345 -U "USERNAME:PASSWORD" https://ipv4.icanhazip.com
```

`socks5://` resolves the hostname on your machine and sends the proxy an IP. `socks5h://` sends the hostname and lets the proxy resolve it. Use `socks5h` when the answer should match the proxy's country, since CDNs return different edge servers by resolver location. Proxy-Cheap covers the difference in its [SOCKS5 and SOCKS5H article](https://support.proxy-cheap.com/hc/en-us/articles/28061797538333-What-is-the-difference-between-SOCKS5-and-SOCKS5H).

Python's standard library has no SOCKS client, which is why the scripts here use HTTP. For SOCKS5 in Python, install `requests[socks]` and pass a `socks5h://` URL as the proxy.

## Static or rotating: decide by session shape

The choice comes down to whether the target should see one visitor or many.

| Job | Session shape | Pick | Why |
|---|---|---|---|
| [Social media account management](https://www.proxy-cheap.com/use-cases/social-media-management) | Long, signed in | Static | Each account keeps a consistent, location accurate IP |
| [Ad verification](https://www.proxy-cheap.com/use-cases/ad-verification) per market | Repeated visits from one market | Static | The same vantage point makes placements comparable day to day |
| Localized rank checks | Scheduled, small volume | Static | A stable IP keeps results consistent between runs |
| Localization QA | Interactive, one tester | Static | The session survives a full test pass |
| Large crawls of publicly available data | Short, stateless, high volume | [Rotating residential proxies](https://www.proxy-cheap.com/services/rotating-residential-proxies) | Volume spreads over a large pool, with per GB billing |
| Bulk fetches from open catalogs and docs | Stateless, throughput first | [Datacenter proxies](https://www.proxy-cheap.com/services/datacenter-proxies) | Highest throughput per dollar |

A quick test: if you would be annoyed to have cookies wiped halfway through the job, you want static.

## Before you buy a static residential proxy

Six checks, in the order they bite:

1. **Count identities, not requests.** Rotating plans are sized in gigabytes. Static plans are sized in addresses. Twenty accounts means twenty IPs on a plan with one user per IP.
2. **Choose the country and ISP carefully.** Both are set when you order, from the [available locations](https://www.proxy-cheap.com/locations). The ISP stays with the proxy for its whole lifetime, so a wrong pick usually means a new order.
3. **Start on the shortest term.** Run `check_static_ip.py` and your real workload against the target for a week before you attach an account to the address.
4. **Decide the auth method per environment.** Fixed outbound IP, use the whitelist. Anything else, use the password.
5. **Decide the protocol up front.** One protocol per proxy, and switching it changes the port.
6. **Turn on auto extend for any IP that carries an identity.** A lapsed rental is the one failure a retry cannot fix.

Ordering can be scripted as well. The v2 order flow is four calls: list services, fetch the options for one service, price a configuration, then execute it. The service id for this product is `static-residential-ipv4`, and its plan ids are `basic`, `standard` (shown as Dedicated in the dashboard) and `premium`.

```bash
curl -s https://api.proxy-cheap.com/v2/order -H "Accept: application/json"
```

Proxy-Cheap bills per IP with no setup costs, and takes cards, PayPal and crypto. Current prices are on the product page linked at the top.

## FAQ

### Does a static residential proxy ever change its IP?

Not on its own. The IP stays the same for as long as the rental is active. It changes only if the rental lapses and you order again, which is why auto extend matters for pinned identities.

### What is a static IP proxy?

Any proxy whose exit address does not rotate. Static residential proxies are the kind where that fixed address is registered to a consumer ISP. A static datacenter proxy is also a static IP proxy, on a hosting network.

### Are static residential proxies and ISP proxies the same thing?

In most catalogs, yes. Both names describe ISP registered addresses hosted on datacenter hardware. Proxy-Cheap labels the product "Static Residential (ISP)" in its API.

### How many static IPs do I need?

One per identity that has to look consistent, plus spares. For stateless work, divide your peak concurrency by the connection ceiling of one proxy and round up.

### Can two workers share one static proxy?

Yes, as long as their combined open connections stay under the ceiling. Size the semaphore for the total, not per worker, or split the budget between them.

### Can I move a proxy to a different ISP later?

The ISP is fixed at checkout. Proxy-Cheap support may help when the order was a mistake, so plan on choosing it correctly the first time.

### Why does my script get a 407?

The proxy did not accept your authentication. Either the username and password are wrong, or the proxy is set to IP whitelist and your current public IP is not on the list.

### Is using a static residential proxy legal?

Routing your own traffic through a proxy to reach publicly available content is generally lawful. What you do through it still has to follow the law and each site's terms. Proxy-Cheap discusses this in its article on [whether proxies are legal](https://www.proxy-cheap.com/blog/are-proxies-legal). This is not legal advice.

## License

MIT

---

*This is a personal documentation repo, not an official Proxy-Cheap project. Plan limits, endpoints and field names were read from the public product page, support articles and API documentation on 16 November 2026 and can change, so confirm them on the live pages before relying on them. The IPs in the examples come from documentation ranges and are placeholders. The scripts use standard proxy configuration and work with any provider that gives you a host, a port and credentials.*
