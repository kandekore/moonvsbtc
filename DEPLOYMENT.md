# DEPLOYMENT.md

Deploying **Bitcoin vs The Moon** to a LiteSpeed + MySQL host.

---

## 0. Stated assumptions

These are assumptions, not verified facts about your server. Check each one and
adjust; where I could not verify something from the repository I have said so
rather than guessing silently.

| Assumption | Why | If it's wrong |
|---|---|---|
| LiteSpeed (LSWS) as the web server, most likely under cPanel | The brief says LiteSpeed; the repo's existing `deploy/` files target cPanel/WHM | Use **Path B** below |
| cPanel **Setup Python App** is available (Passenger/LSAPI, CloudLinux) | Standard on cPanel + LiteSpeed hosts | Use **Path B** (standalone + reverse proxy) |
| Python **3.11+** available | Code uses modern typing syntax (`str \| None`) | 3.10 is the floor; below that it will not import |
| MySQL 5.7+ or MariaDB 10.3+ | utf8mb4 and InnoDB defaults | Any version supporting `utf8mb4` is fine |
| No compiler toolchain on the host | Shared hosting usually lacks one | We use **PyMySQL** (pure Python), not `mysqlclient` |
| Outbound HTTPS allowed | Needed for yfinance, RSS feeds and the OpenAI API | Without it, market/news degrade to cached values |

`deploy/apache-moonvsbtc.conf` and `deploy/cpanel-app-proxy.conf` in this repo
target the **old** Streamlit-only setup. They are superseded by this document.

---

## 1. MySQL setup

Via **cPanel → MySQL® Databases**, or on the command line:

```sql
CREATE DATABASE `cpuser_btcmoon`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'cpuser_btcmoon'@'localhost'
  IDENTIFIED BY 'a-long-random-password';

GRANT ALL PRIVILEGES ON `cpuser_btcmoon`.* TO 'cpuser_btcmoon'@'localhost';
FLUSH PRIVILEGES;
```

Creating the **database** as `utf8mb4` means every table inherits it, so no
per-table charset options are needed. The connection also forces
`charset=utf8mb4` (see `btcmoon/db.py`).

Verify:

```sql
SELECT default_character_set_name, default_collation_name
FROM information_schema.SCHEMATA WHERE schema_name = 'cpuser_btcmoon';
-- expect: utf8mb4 | utf8mb4_unicode_ci
```

---

## 2. Path A — cPanel "Setup Python App" (recommended)

This runs the Flask app under Passenger/LSAPI. LiteSpeed serves it directly; no
reverse proxy, no long-running process to babysit.

### 2.1 Create the application

**cPanel → Setup Python App → Create Application**

| Field | Value |
|---|---|
| Python version | 3.11 or newer |
| Application root | `moonvsbtc` |
| Application URL | your domain (e.g. `bitcoinvsthemoon.com`) |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

cPanel creates a virtualenv and shows an **"Enter to the virtual environment"**
command near the top of the page. It looks like:

```
source /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/activate && cd /home/CPUSER/moonvsbtc
```

**Copy that line — every command below assumes you have run it.**

### 2.2 Deploy the code

```bash
cd ~/moonvsbtc
git clone https://github.com/kandekore/moonvsbtc.git .
# or: git remote add origin ... && git pull origin main
```

### 2.3 Install dependencies

```bash
source /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/activate && cd /home/CPUSER/moonvsbtc
pip install --upgrade pip
pip install -r requirements.txt
```

`scipy`, `numpy` and `pandas` ship manylinux wheels, so this needs no compiler.
If pip tries to build from source, your Python is too new for the current wheels
— drop to the previous minor version.

### 2.4 Configure

```bash
cp .env.example .env
chmod 600 .env          # important: it holds the DB password and API key
nano .env
```

Fill in at minimum:

```ini
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
DATABASE_URL=mysql+pymysql://cpuser_btcmoon:PASSWORD@localhost/cpuser_btcmoon?charset=utf8mb4
SITE_URL=https://bitcoinvsthemoon.com
SESSION_COOKIE_SECURE=true
OPENAI_API_KEY=            # optional — see section 6
```

If the password contains `@ : / ? # [ ]`, percent-encode it:

```bash
python -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" 'p@ss/word'
```

> cPanel's Python App UI also has an **Environment variables** panel. You may use
> either that or `.env`. Do not split the same variable across both — `.env` wins,
> because `load_dotenv()` does not override variables already in the environment,
> but the reverse is confusing to debug. Pick one. `.env` is simpler.

### 2.5 Create the schema

```bash
alembic upgrade head
```

Then seed and create your account:

```bash
python manage.py bootstrap        # frozen protocols, news sources, settings
python manage.py create-admin     # prompts for email + password (min 12 chars)
python manage.py seed-archive     # Aug/Sep 2026 reconstructed DRAFTS
python manage.py status           # health check — read the output
```

`seed-archive` imports **drafts only**. Nothing is public until you publish it in
`/admin/`.

### 2.6 Static files

Flask serves `/static/` itself, which is fine at this traffic level. To let
LiteSpeed serve them directly instead, add to `public_html/.htaccess` **above**
the Passenger rules:

```apache
# Serve the app's static assets straight from disk.
Alias /static /home/CPUSER/moonvsbtc/btcmoon/static
<Directory "/home/CPUSER/moonvsbtc/btcmoon/static">
    Require all granted
    Options -Indexes
</Directory>
<IfModule mod_headers.c>
    <FilesMatch "\.(css|js|svg|png|jpg|woff2)$">
        Header set Cache-Control "public, max-age=2592000"
    </FilesMatch>
</IfModule>
```

### 2.7 Restart

**Any code or `.env` change requires a restart:**

```bash
mkdir -p ~/moonvsbtc/tmp
touch ~/moonvsbtc/tmp/restart.txt
```

Or click **Restart** in the Setup Python App page.

### 2.8 Verify

```bash
curl -sI https://bitcoinvsthemoon.com/               | head -1   # 200
curl -s  https://bitcoinvsthemoon.com/robots.txt                  # Disallow: /admin/
curl -s  https://bitcoinvsthemoon.com/sitemap.xml    | head -3    # <?xml
curl -sI https://bitcoinvsthemoon.com/admin/         | head -1    # 302 → login
```

---

## 3. Path B — standalone process behind LiteSpeed

Use this if Setup Python App is unavailable, or you prefer gunicorn.

### 3.1 Run the app

```bash
pip install gunicorn
gunicorn -w 3 -b 127.0.0.1:8000 --timeout 60 \
         --access-logfile ~/logs/btcmoon-access.log \
         --error-logfile  ~/logs/btcmoon-error.log \
         wsgi:application
```

Keep it alive with systemd (root access) — see `deploy/moonvsbtc.service` for the
pattern, changing `ExecStart` to the gunicorn line above. Without root, use
`screen`/`tmux` plus a cron `@reboot` line.

### 3.2 Proxy from LiteSpeed

**WHM → Apache Configuration → Include Editor → Pre Main Include**, or a
per-domain include. LiteSpeed reads Apache's proxy directives:

```apache
<IfModule proxy_module>
    ProxyPreserveHost On
    ProxyRequests Off
    ProxyPass        /static/ !
    ProxyPass        / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/
    RequestHeader set X-Forwarded-Proto "https"
</IfModule>
```

Then rebuild and restart:

```bash
/scripts/rebuildhttpdconf && systemctl restart lsws
```

If you terminate HTTPS at LiteSpeed (you will), add `ProxyFix` so Flask sees the
real scheme — otherwise `url_for(_external=True)` emits `http://`:

```python
# wsgi.py
from werkzeug.middleware.proxy_fix import ProxyFix
application.wsgi_app = ProxyFix(application.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

---

## 4. Cron jobs

**cPanel → Cron Jobs.** Every job runs standalone: no browser session, no web
server, no open terminal. All are **idempotent** — a second run of the same
logical job for the same period is recorded as *skipped*, not duplicated.

Set the cron environment once at the top:

```
MAILTO=you@example.com
```

Then, substituting your real paths:

```cron
# --- Bitcoin vs The Moon ------------------------------------------------
# Morning research briefing — 07:00 Europe/London
0 7 * * *    cd /home/CPUSER/moonvsbtc && /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/python -m jobs.morning_brief >> /home/CPUSER/logs/btcmoon-cron.log 2>&1

# Evening research briefing — 18:00 Europe/London
0 18 * * *   cd /home/CPUSER/moonvsbtc && /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/python -m jobs.evening_brief >> /home/CPUSER/logs/btcmoon-cron.log 2>&1

# News/RSS ingestion — hourly, deterministic, zero AI cost
15 * * * *   cd /home/CPUSER/moonvsbtc && /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/python -m jobs.ingest_news >> /home/CPUSER/logs/btcmoon-cron.log 2>&1

# Tomorrow's BTC natal outlook, created as a DRAFT for review
0 19 * * *   cd /home/CPUSER/moonvsbtc && /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/python -m jobs.daily_outlook >> /home/CPUSER/logs/btcmoon-cron.log 2>&1

# Daily market snapshot
5 0 * * *    cd /home/CPUSER/moonvsbtc && /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/python -m jobs.snapshot_market >> /home/CPUSER/logs/btcmoon-cron.log 2>&1

# Re-measure every frozen protocol against the latest data (never edits a protocol)
30 0 * * *   cd /home/CPUSER/moonvsbtc && /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/python -m jobs.evaluate_protocols >> /home/CPUSER/logs/btcmoon-cron.log 2>&1
```

**Notes.**

- `cd` first. `.env` is read from the working directory.
- Use the **virtualenv's** Python, not `/usr/bin/python3`.
- Server cron usually runs **UTC**. Check with `date`; if it is UTC, use
  `0 6 * * *` / `0 17 * * *` for BST and shift by an hour at the DST change, or
  set `CRON_TZ=Europe/London` at the top of the crontab if your cron supports it.
- `daily_outlook` deliberately creates a **draft**. It has a `--publish` flag;
  it is intentionally not in the recommended cron line, because nothing should
  publish itself.
- Every run is logged to the `scheduled_job_runs` table and visible at
  `/admin/jobs/`.

Test one by hand before trusting cron:

```bash
cd ~/moonvsbtc && python -m jobs.ingest_news
```

---

## 5. Updating a live deployment

```bash
source /home/CPUSER/virtualenv/moonvsbtc/3.11/bin/activate && cd /home/CPUSER/moonvsbtc

# 1. Back up the database FIRST
mysqldump -u cpuser_btcmoon -p --single-transaction --routines \
  cpuser_btcmoon > ~/backups/btcmoon-$(date +%F-%H%M).sql

# 2. Pull
git pull origin main

# 3. Dependencies (only if requirements.txt changed)
pip install -r requirements.txt

# 4. Migrate
alembic upgrade head

# 5. Restart
touch tmp/restart.txt

# 6. Verify
python manage.py status
curl -sI https://bitcoinvsthemoon.com/ | head -1
```

Roll back a migration with `alembic downgrade -1`. Roll back code with
`git checkout <previous-sha>` followed by a restart.

---

## 6. Credentials you need to provide

| Variable | Required? | What happens without it |
|---|---|---|
| `SECRET_KEY` | **Yes** | Sessions are signed with an insecure default. Set it. |
| `DATABASE_URL` | **Yes** | Falls back to a local SQLite file — not acceptable in production. |
| `SITE_URL` | **Yes** | Canonical URLs and the sitemap point at the wrong host. |
| `OPENAI_API_KEY` | **No** | **The system works without it.** Briefings, outlooks and the Companion return a complete deterministic summary built from market, lunar, natal and protocol data, at zero cost. Adding the key later activates the AI write-up with no other change. |
| `COINGECKO_API_KEY` | **No** | Unused. yfinance needs no credential. The adapter exists so the provider can be swapped without touching research code. |
| `RATELIMIT_STORAGE_URI` | **No** | Defaults to in-process memory. Fine for one worker; point at Redis if you run several. |

**Get an OpenAI key** at <https://platform.openai.com/api-keys>, then:

```bash
nano .env          # set OPENAI_API_KEY=sk-...
touch tmp/restart.txt
python manage.py status      # should report "AI status: available"
```

Set `AI_MONTHLY_BUDGET_USD` before you do. The ceiling is enforced before every
call, so a runaway loop cannot produce a surprise bill. Watch `/admin/costs/`.

---

## 7. The optional Streamlit dashboard

`app.py` is the original interactive research dashboard. It is **unchanged** and
still works, but the public site, admin, Companion and every cron job run
without it. It is not required and is not part of this deployment.

To run it as a private tool on a separate port:

```bash
pip install -r requirements-streamlit.txt
streamlit run app.py --server.port=8501 --server.address=127.0.0.1 \
  --server.headless=true --server.baseUrlPath=research
```

If you expose it, **put it behind HTTP auth** — it has no authentication of its
own. `robots.txt` does not block `/research/` (that path is the public research
journal), so use a different prefix and add a `Disallow` line if you proxy it.

---

## 8. Troubleshooting

**500 on every page**
Check the Passenger log (cPanel → Setup Python App shows the path, usually
`~/logs/` or `stderr.log` in the app root). Most common causes: `.env` missing or
unreadable, or `DATABASE_URL` wrong.

**`ModuleNotFoundError: No module named 'btcmoon'`**
Passenger is not running from the app root. `passenger_wsgi.py` handles this, so
check that the **Application startup file** is `passenger_wsgi.py` and the
**Entry point** is `application`.

**`(2003, "Can't connect to MySQL server")`**
Use `localhost`, not `127.0.0.1` — on cPanel the former uses the unix socket.
Confirm the user is granted on the database.

**`(1045, "Access denied")`**
Almost always an unencoded special character in the password. Percent-encode it.

**`RuntimeError: cryptography is required`**
MySQL 8 `caching_sha2_password`. `pip install cryptography` (already in
`requirements.txt`).

**Changes don't appear**
`touch tmp/restart.txt`. Passenger caches aggressively.

**Cron jobs silently do nothing**
Check `/admin/jobs/`. A `skipped` status means the idempotency key already
succeeded — that is correct behaviour. Force one with `--force`.

**Market data unavailable**
The host may block outbound HTTPS. The system degrades to the cached CSV in
`.cache/` rather than failing. Confirm with:
`python -c "from btcmoon.market_data import technical_context; print(technical_context())"`

**News ingestion returns SSL errors**
Feeds are fetched with `requests` (which uses certifi) precisely to avoid this.
If it still fails, the host is intercepting TLS; set `REQUESTS_CA_BUNDLE`.

**Everything looks right but pages 404**
Check the Application URL in Setup Python App matches the domain, and that
`public_html/.htaccess` has not been overwritten by another tool.

---

## 9. Security checklist

- [ ] `.env` is `chmod 600` and is **not** in git (it is in `.gitignore`)
- [ ] `SECRET_KEY` is a fresh random value, not the default
- [ ] `SESSION_COOKIE_SECURE=true` and HTTPS is live (cPanel AutoSSL)
- [ ] `FLASK_DEBUG=false`
- [ ] Admin password is 12+ characters and unique
- [ ] `robots.txt` disallows `/admin/` and `/account/` (it does, by default)
- [ ] `AI_MONTHLY_BUDGET_USD` is set to a figure you are happy to lose
- [ ] Database backups are scheduled
- [ ] There is **no public admin signup** — admins are created only by
      `python manage.py create-admin`
