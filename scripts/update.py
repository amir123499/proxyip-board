#!/usr/bin/env python3
"""
proxyip-board updater.

- Fetches the NiREvil/vless daily proxy IP list
- Probes TCP/443 (3 attempts) for health + latency
- Geo-resolves healthy IPs via ip-api.com batch API
- Writes data.json
"""
import asyncio
import json
import re
import sys
import time
import urllib.request

DAILY_URL = "https://raw.githubusercontent.com/NiREvil/vless/main/sub/ProxyIP-Daily.md"
GEO_URL = "http://ip-api.com/batch?fields=query,status,country,countryCode,city,isp"
ATTEMPTS = 3
TIMEOUT = 3.0
CONCURRENCY = 400
PORT = 443


def log(*a):
    print(*a, flush=True)


def valid_ip(ip):
    p = ip.split(".")
    return len(p) == 4 and all(x.isdigit() and 0 <= int(x) <= 255 for x in p)


def fetch_daily():
    log("fetching daily list...")
    req = urllib.request.Request(
        DAILY_URL, headers={"User-Agent": "proxyip-board/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    md = {}  # ip -> {isp, city} fallback info from the markdown table
    ips = []
    for line in text.splitlines():
        if not line.startswith("| <pre>"):
            continue
        m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
        if not m or not valid_ip(m.group(1)):
            continue
        ip = m.group(1)
        cells = [c.strip() for c in line.split("|")]
        isp = cells[2] if len(cells) > 2 else ""
        loc = cells[3] if len(cells) > 3 else ""
        city = ""
        if "," in loc:
            city = loc.split(",")[-1].strip()
        elif loc and loc.lower() != "unknown":
            city = loc.strip()
        if city.lower() == "unknown":
            city = ""
        if ip not in md:
            md[ip] = {"isp": isp, "city": city}
            ips.append(ip)
    log(f"parsed {len(ips)} unique ips")
    return ips, md


async def probe_one(ip):
    ok = 0
    lats = []
    for _ in range(ATTEMPTS):
        try:
            t0 = time.perf_counter()
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, PORT), TIMEOUT)
            lats.append((time.perf_counter() - t0) * 1000)
            ok += 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception:
            pass
    avg = round(sum(lats) / len(lats), 1) if lats else None
    return {"ip": ip, "health": ok, "latency": avg}


async def probe_all(ips):
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0

    async def worker(ip):
        nonlocal done
        async with sem:
            r = await probe_one(ip)
        done += 1
        if done % 500 == 0:
            log(f"probed {done}/{len(ips)}")
        return r

    return await asyncio.gather(*(worker(ip) for ip in ips))


def geo_lookup(ips):
    """Resolve country/city/isp via ip-api.com batch (100 IPs per request)."""
    out = {}
    total_batches = (len(ips) + 99) // 100
    for i in range(0, len(ips), 100):
        chunk = ips[i:i + 100]
        payload = json.dumps([{"query": ip} for ip in chunk]).encode()
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    GEO_URL, data=payload,
                    headers={"Content-Type": "application/json",
                             "User-Agent": "proxyip-board/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    rows = json.loads(r.read().decode())
                for row in rows:
                    if row.get("status") == "success":
                        out[row["query"]] = {
                            "country": row.get("country") or "",
                            "cc": (row.get("countryCode") or "").upper(),
                            "city": row.get("city") or "",
                            "isp": row.get("isp") or "",
                        }
                break
            except Exception as e:
                log(f"geo batch {i // 100 + 1}/{total_batches} "
                    f"attempt {attempt + 1} failed: {e}")
                time.sleep(5 * (attempt + 1))
        time.sleep(2)  # stay comfortably under the rate limit
        log(f"geo {min(i + 100, len(ips))}/{len(ips)}")
    return out


def main():
    t0 = time.time()
    ips, md = fetch_daily()
    if not ips:
        log("no ips found, aborting")
        sys.exit(1)
    results = asyncio.run(probe_all(ips))
    results.sort(key=lambda r: (-r["health"],
                                r["latency"] if r["latency"] is not None else 1e9))
    healthy = [r["ip"] for r in results if r["health"] > 0]
    log(f"healthy: {len(healthy)}/{len(results)}, geo-resolving...")
    geo = geo_lookup(healthy)
    items = []
    for r in results:
        g = geo.get(r["ip"], {})
        m = md.get(r["ip"], {})
        items.append({
            "ip": r["ip"],
            "health": r["health"],
            "of": ATTEMPTS,
            "latency": r["latency"],
            "country": g.get("country") or "",
            "cc": g.get("cc") or "",
            "city": g.get("city") or m.get("city") or "",
            "isp": g.get("isp") or m.get("isp") or "",
        })
    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "NiREvil/vless ProxyIP-Daily",
        "total": len(items),
        "healthy": len(healthy),
        "items": items,
    }
    with open("data.json", "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"wrote data.json: {len(items)} items in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
