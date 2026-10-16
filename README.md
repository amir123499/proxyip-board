# Proxy IP Board

A public, auto-updating proxy IP list — like the BPB panel's proxy IP table, but no login needed.

- **Live page:** https://amir123499.github.io/proxyip-board/
- **Data:** `data.json`, refreshed every 6 hours by GitHub Actions (`.github/workflows/update.yml`)
- **Source IPs:** [NiREvil/vless](https://github.com/NiREvil/vless) daily proxy list

Each run TCP-connects to port 443 (3 attempts per IP) to measure health + latency,
then geo-resolves the healthy IPs (country / city / ISP) via ip-api.com.

Latency is measured from GitHub's runners — good for comparing IPs against each
other; your own ping may differ.
