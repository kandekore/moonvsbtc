# 🌕 Bitcoin vs the Moon

An interactive dashboard that tests a market-lore hypothesis:

- **Full moon → local top** in Bitcoin
- **New moon → local bottom** in Bitcoin

…and, crucially, **measures the average lag** between each moon and the real
turning point (the tops looked like they came a few days *after* the full moon),
then uses that average ± spread to **predict future tops and bottoms**.

## How it works

1. **Price** — full BTC-USD daily history from Yahoo Finance (`yfinance`).
2. **Moon phases** — every full/new moon across the range (`ephem`).
3. **True swing pivots** — genuine local highs/lows detected with
   `scipy.signal.find_peaks` (minimum prominence + spacing), *not* just the max
   in a fixed window.
4. **Matching** — each moon is matched to the nearest pivot of the correct type
   within a max lag, recording the **signed offset** (− before / + after).
5. **Statistics** — mean / median / std of the offsets → your "N days after"
   number with an uncertainty band.
6. **Prediction** — upcoming moons + mean offset → predicted turning-point dates,
   drawn as shaded ± 1σ windows on the chart. The search looks back one lunar
   cycle, so the phase you're **currently in** (e.g. a new moon that was
   yesterday) still appears and is flagged 🟢 **active** while its window is live.

## Controls & defaults

Everything is tunable live in the sidebar. The **defaults are set to isolate the
biggest, cleanest swings** — one turning point per lunar cycle — because that's
where the moon relationship is most likely to show:

| Control | Default | Meaning |
|---------|---------|---------|
| **Price history** | Max (2014→) | How far back to pull BTC data. Analysis always uses the full range. |
| **Min days between pivots** | **30** | Minimum spacing between swing pivots. 30 ≈ one per lunar cycle, so we don't count intra-cycle noise. |
| **Min prominence (% of price)** | **15%** | How far a swing must stand out to count. 15% keeps only major tops/bottoms. |
| **Max moon→pivot lag** | **14 days** | A moon only matches a pivot within this many days. 14 ≈ half a lunar cycle — the point where the moon flips to the opposite phase, so a top can't be "claimed" by the wrong moon. |
| **Prediction horizon** | 120 days | How far ahead to project future turning points. |
| **Log price axis** | on | Log scale so early-history moves are visible. |

Lowering the spacing/prominence surfaces more (smaller) pivots and generally
pulls the average lag back toward zero; the maxed-out defaults give the widest,
most selective windows.

## View & display

- **Zoom / date range** — range-selector buttons (1M/3M/6M/YTD/1Y/All), a range
  slider under the chart, and a sidebar **date-range picker** for an exact
  window. The view defaults to the last 12 months (plus the prediction horizon).
  The y-axis auto-fits to whatever's in view. *Zooming only changes the view —
  all stats and predictions still use full history.*
- **Display toggle** — **Chart / Table / Both**. The table shows daily price with
  **Full moon / New moon / Swing high / Swing low** flags, an "only event days"
  filter, and CSV download.
- **Offset histograms** — show exactly how tops/bottoms cluster around the moon,
  so you can judge whether the average lag is a real skew or just noise.

## Run it

```bash
# first time only
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# launch the app
.venv/bin/streamlit run app.py
```

Then open the URL it prints (usually http://localhost:8501).

Run the analysis engine standalone (no UI) for a quick text summary:

```bash
.venv/bin/python moon_engine.py
```

## SEO & site architecture

Streamlit apps are **not indexable** — they render client-side over a WebSocket,
the `<head>` is fixed, and there are no crawlable URLs. So the project is split
into two tiers, both served from **one domain on the Apache VPS**:

```
bitcoinvsthemoon.com/       → static crawlable HTML site (docs/)  ← all the SEO weight
bitcoinvsthemoon.com/app/   → the interactive Streamlit tool      ← reverse-proxied
```

The **`docs/`** folder is a fast, self-contained static site (system fonts, no
external requests) carrying the search visibility:

| Page | Purpose |
|------|---------|
| `docs/index.html` | Landing page — hypothesis, key findings, FAQ, CTA to the tool. |
| `docs/moon-phases.html` | Content: the lunar cycle, full/new moons, market lore. |
| `docs/bitcoin-history.html` | Content: halving cycles, bull/bear markets, volatility. |
| `docs/methodology.html` | Content: swing-pivot detection, signed-lag stats, prediction. |
| `docs/robots.txt`, `docs/sitemap.xml` | Crawl directives + sitemap. |
| `docs/assets/og-image.png` | 1200×630 Open Graph share image (regenerate with `tools/make_og_image.py`). |
| `docs/assets/style.css`, `favicon.svg` | Shared styling + icon. |

Every page ships: a unique keyword-rich `<title>` + meta description, canonical
URL, Open Graph + Twitter Card tags, and **JSON-LD structured data**
(`WebSite`, `WebApplication`, `Article`/`TechArticle`, `BreadcrumbList`,
`FAQPage`) for rich results.

> **URLs are set for `https://bitcoinvsthemoon.com`.** If the domain changes,
> find-and-replace that host across `docs/` and `deploy/`, then regenerate the OG
> image with `tools/make_og_image.py`.

## Deployment (Apache VPS — site + tool on one domain)

Point `bitcoinvsthemoon.com` (and `www`) DNS at the VPS, then:

```bash
# 1. code + dependencies
sudo git clone <your-repo> /opt/moonvsbtc && cd /opt/moonvsbtc
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt

# 2. run the Streamlit tool as a service (already sets --server.baseUrlPath=app)
sudo cp deploy/moonvsbtc.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now moonvsbtc

# 3. Apache: static docs/ at /, tool proxied at /app/ (WebSocket-aware)
sudo a2enmod proxy proxy_http proxy_wstunnel rewrite headers
sudo cp deploy/apache-moonvsbtc.conf /etc/apache2/sites-available/bitcoinvsthemoon.conf
sudo a2ensite bitcoinvsthemoon && sudo systemctl reload apache2

# 4. HTTPS (free, auto-renewing)
sudo certbot --apache -d bitcoinvsthemoon.com -d www.bitcoinvsthemoon.com
```

Then submit `https://bitcoinvsthemoon.com/sitemap.xml` in
[Google Search Console](https://search.google.com/search-console).

**Updating later:** `cd /opt/moonvsbtc && sudo git pull`, then
`sudo systemctl restart moonvsbtc` (static `docs/` changes are live immediately).

### Deploying via cPanel Git Version Control

The repo ships a **`.cpanel.yml`** so cPanel can publish the static site for you.

1. **Static site (Git module):** in cPanel » *Git Version Control*, clone this
   repo, then edit `DEPLOYPATH` in `.cpanel.yml` to your domain's document root
   (see cPanel » *Domains*). Each *Update from Remote* → *Deploy HEAD Commit*
   copies `docs/` into that docroot. That alone makes the crawlable SEO site live.
2. **Interactive tool (one-time, over SSH):** the Git module only copies files —
   it can't run Python. So set the Streamlit process up once:
   - Install deps in a venv and start it as a service:
     `--server.baseUrlPath=app` on `127.0.0.1:8501` (use `deploy/moonvsbtc.service`
     if you have root/WHM, or cPanel's *Application Manager* / a `screen` session).
   - Add the reverse proxy from **`deploy/cpanel-app-proxy.conf`** via
     WHM » *Apache Configuration* » *Include Editor* (don't edit the vhost directly
     on cPanel), then rebuild + restart Apache.
   - Enable `mod_proxy`, `mod_proxy_http`, `mod_proxy_wstunnel`, `mod_rewrite` in
     EasyApache 4 if they aren't already.

If you don't have WHM/root on the cPanel box, the static site still works fully;
the `/app/` tool needs that proxy + a long-running process, so host it on the VPS
side or a subdomain you can proxy.

### Alternative: Docker for just the tool

```bash
docker build -t moonvsbtc .
docker run -d --name moonvsbtc -p 8501:8501 --restart unless-stopped moonvsbtc
```
Still front it with the Apache vhost in `deploy/` for the static site + HTTPS.

Deployment files: `Dockerfile`, `.dockerignore`, `.streamlit/config.toml`,
`deploy/moonvsbtc.service`, `deploy/apache-moonvsbtc.conf`.

## Files

| File | Purpose |
|------|---------|
| `moon_engine.py` | Pure analysis engine (data, moons, pivots, matching, stats, prediction). |
| `app.py` | Streamlit + Plotly dashboard. |
| `requirements.txt` | Dependencies. |
| `btc_moon_analysis.py`, `btcvsmoon.py` | Original prototype scripts (kept for reference). |

## ⚠️ Disclaimer

Educational / exploratory only. Lunar phases have no established causal effect on
markets — this is pattern-fitting on historical data, **not financial advice**.
