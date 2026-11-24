# Dhaka Price Tracker — Implementation Plan

> Hand-off document for Claude Code. Work through the tickets in order, one ticket per session.
> Plan date: 23 Nov 2026. Owner: Kazi.

---

## 1. What we are building

A **local, personal** tool that tracks and predicts two things from a Dhaka point of view:

1. **BAJUS gold prices** (Bangladesh Jewellers Association): 22K, 21K, 18K and traditional, buy and sell.
2. **Airfares from Dhaka (DAC)** to Hanoi (HAN), Bangkok (BKK), Manila (MNL) and Vientiane (VTE).

It joins those prices with context (USD/BDT, world gold XAU/USD, Bangladesh holidays and the Islamic calendar, world news shocks). From that it produces KPIs, pattern analyses and short-horizon predictions, shown on a local dashboard, with email alerts.

### Hard constraints (do not violate)

| Constraint | Meaning for implementation |
|---|---|
| **Zero spend** | No paid APIs, no cloud accounts, no paid tiers. Free, open-source software and free public data only. |
| **Local only** | Everything runs on the owner's machine via Docker Compose. Nothing is deployed. |
| **Manual daily run** | The owner runs `make collect` once a day at a fixed time. There is no always-on scheduler. The machine may be off for days. |
| **Dhaka-based prices** | Fare queries use country = Bangladesh, currency = BDT, origin = DAC. Gold is BAJUS (Bangladesh). |
| **Alerts by email only** | Gmail SMTP with an app password. No Telegram, no push. |
| **Polite collection** | Low request rates, one run per day, no CAPTCHA solving, no login bypass, no proxy rotation to evade blocks. If a site blocks us, log it and move on. |

### What "prediction" means

- **Gold:** will BAJUS change the 22K price within the next 7 days, and in which direction? (BAJUS reprices in discrete jumps, not continuously.)
- **Fares:** for a given route and departure date, is it better to **buy now or wait**? Concretely: will the fare drop by at least 5% before 14 days to departure?

Predictions start as **transparent rules**. They are only replaced by a model after a backtest shows the model beats the rule.

---

## 2. Architecture

```
            ┌────────────── make collect (run by hand, once a day) ──────────────┐
            │                                                                     │
 Sources    │  collectors (one module per source)                                 │
 ───────    │     │                                                               │
 goldr.org  │     ├──► data/raw/<source>/<YYYY-MM-DD>/*.gz   (raw snapshots)      │
 BAJUS site │     └──► Postgres: raw.*, stg.*                (parsed rows)        │
 XAU/USD    │                                                                     │
 USD/BDT    │  dbt run + dbt test        ──► feat.*                               │
 Google Fl. │  python -m models.score    ──► pred.*                               │
 ShareTrip  │  python -m alerts.send     ──► email (alerts, run summary, digest)  │
 GoZayaan   │  pg_dump                   ──► backups/                             │
 GDELT      │                                                                     │
 calendar   └─────────────────────────────────────────────────────────────────────┘

 Metabase (always available at http://localhost:3000 when compose is up) reads Postgres.
```

### Why each piece (keep these reasons in mind when making trade-offs)

| Decision | Choice | Why |
|---|---|---|
| Runtime | Docker Compose on the owner's machine | Internal tool with nothing to deploy. No billing. Reproducible. |
| Trigger | `make collect` by hand at a fixed time | No always-on machine needed. The same time every day removes time of day as a variable in fare data. |
| Missed days | Gold is backfilled from goldr history on the next run. Fare gaps are **flagged, never invented**. | Past BAJUS prices are published. Past fares are gone once missed. |
| Database | Postgres 16 | The collector writes while Metabase reads. Owner prefers Postgres. |
| Raw snapshots | Gzipped files on disk before parsing | When a site changes its HTML, the parser breaks but history does not. Fix the parser, then re-parse old snapshots. |
| Transforms | dbt with the Postgres adapter | Versioned SQL with tests and dependencies. |
| Gold model | Change-event model, not a daily series | A daily BAJUS series is mostly flat lines. The real question is when the next jump comes and which way. |
| Prediction | Rules first, then scikit-learn / LightGBM | With weeks of fare data, percentile rules beat models. |
| Dashboard | Metabase | Free, point-and-click charts on Postgres. |
| Backups | `pg_dump` after every run | Fare history cannot be recollected. |

---

## 3. Tech stack

| Area | Tool | Notes |
|---|---|---|
| Language | Python 3.12 | Managed with **uv** (`uv sync`, `uv run`) |
| Lint / format | ruff | Line length 100 |
| Tests | pytest | Fixtures in `tests/fixtures/<source>/` |
| HTTP | httpx | Shared client only (see T0.3) |
| HTML parsing | selectolax or BeautifulSoup4 | Pick one and use it everywhere |
| Browser scraping | Playwright (Chromium) | Only for ShareTrip and GoZayaan |
| Google Flights | An unofficial open-source client (e.g. `fast-flights`) | Wrap it behind our own interface so it can be swapped |
| DB access | SQLAlchemy 2 Core + psycopg 3 | No ORM models needed |
| Migrations | Alembic | Creates schemas and staging tables |
| Transforms | dbt-core + dbt-postgres | Builds `feat.*` |
| Models | pandas, scikit-learn, LightGBM | Phase 5 only |
| Config | YAML files + `pydantic-settings` for `.env` | |
| Email | `smtplib` via Gmail SMTP, port 587, STARTTLS | App password in `.env` |
| Dashboard | Metabase (official Docker image) | |
| DB | Postgres 16 (official Docker image) | |

**Rule:** do not add a dependency that is not in this table without asking the owner first.

---

## 4. Repository layout

```
dhaka-price-tracker/
├── README.md
├── IMPLEMENTATION_PLAN.md          # this file
├── Makefile
├── docker-compose.yml
├── Dockerfile                      # collector image (Python + Playwright)
├── pyproject.toml / uv.lock
├── .env.example                    # never commit .env
├── config/
│   ├── routes.yaml                 # fare grid
│   ├── sources.yaml                # per-source enable flag, rate limits, URLs
│   ├── watched_trips.yaml          # trips with target prices (alerts)
│   └── news_topics.yaml            # GDELT queries
├── data/
│   ├── raw/                        # gzipped snapshots (git-ignored)
│   └── seeds/calendar_bd.csv       # holidays, Ramadan, Eid, Puja, wedding season
├── backups/                        # pg_dump files (git-ignored)
├── src/tracker/
│   ├── core/                       # settings, db, fetch client, raw store, run log, units
│   ├── collectors/
│   │   ├── gold_goldr.py
│   │   ├── gold_goldr_history.py
│   │   ├── gold_bajus.py
│   │   ├── xau_spot.py
│   │   ├── fx_usd_bdt.py
│   │   ├── fares_google.py
│   │   ├── fares_sharetrip.py
│   │   ├── fares_gozayaan.py
│   │   ├── fares_duffel.py         # only if T-F2 approves it
│   │   └── news_gdelt.py
│   ├── orchestrator.py             # `make collect` entry point
│   ├── models/                     # rules, training, scoring, backtests
│   └── alerts/                     # email templates and senders
├── migrations/                     # Alembic
├── dbt/                            # dbt project (models, tests, seeds)
├── dashboards/                     # exported Metabase dashboard JSON
└── tests/
    ├── fixtures/
    └── ...
```

---

## 5. Domain facts the code must get right

### Gold units (Bangladesh)

| Unit | In grams | Relation |
|---|---|---|
| 1 bhori (vori) | 11.664 g | — |
| 1 ana | 0.729 g | 1/16 bhori |
| 1 rati | 0.1215 g | 1/6 ana |
| 1 troy ounce | 31.1035 g | — |

- Store everything **per gram** in the database. Convert for display only.
- Sanity check, from goldr on 23 Nov 2026: 22K = ৳16,985/g and ৳1,98,113/bhori. 16,985 × 11.664 ≈ 198,113. ✔

### Buy vs sell price

goldr shows a "sell" (old gold) price equal to the **buy price minus 15%**, per a BAJUS rule. Store both as published. Do not derive one from the other in code. A 22 Nov 2026 goldr article reports a new BAJUS rule (9% deduction on exchange, 15% on sale), so this rule can change.

### Bengali numerals

goldr HTML uses Bengali digits and Indian-style grouping (e.g. `৳১,৯৮,১১৩`). Write one tested helper:

- Map `০১২৩৪৫৬৭৮৯` → `0123456789`
- Strip `৳`, commas and spaces
- Return an `int` (or `Decimal`)

### World-implied local price (key gold feature)

```
world_implied_22k_bdt_per_gram = (xau_usd_per_oz / 31.1035) × 0.916 × usd_bdt
premium_pct = bajus_22k_per_gram / world_implied_22k_bdt_per_gram − 1
```

Hypothesis to verify in Phase 4: when world gold falls and the premium widens beyond its recent band, a BAJUS cut follows within days.

### Currency and time

- All timestamps are stored in **UTC** (`timestamptz`) and shown in `Asia/Dhaka`.
- All fare prices are stored in their **source currency**, plus `price_bdt` converted with that day's USD/BDT from `stg.fx_daily`. Record which rate was used.

---

## 6. Data sources

### Gold

| Source | What | Access | Notes |
|---|---|---|---|
| goldr.org (home) | Current BAJUS prices, all karats and units, buy and sell; the USD rate goldr used | The JSON feed behind goldr's widget scripts (`https://www.goldr.org/price.ultra.js`, `/widget.js`, `/price.js`); HTML as fallback | **G1:** find the real data endpoint in those scripts or the browser network tab |
| goldr.org/gold-price-history-in-bangladesh/ | Past BAJUS prices | History widget feed or HTML | Backfill and gap-fill |
| goldr.org/spot-gold-price-live/ | World spot gold | HTML / feed | Candidate XAU source |
| BAJUS official website | The original announcement goldr copies | HTML | Daily cross-check and fallback |
| Bangladesh Bank | USD/BDT reference rate | HTML / CSV | Daily |

### Airfares

| Source | Access | Role | Notes |
|---|---|---|---|
| Google Flights | Unofficial client, `gl=BD`, currency BDT | **Primary** | Can break without notice. Wrap behind an interface. |
| ShareTrip | Playwright | Local taka prices | Lighter grid. Screenshot on parse failure. |
| GoZayaan | Playwright | Local taka prices | Lighter grid. Screenshot on parse failure. |
| Duffel | Official REST API | **Optional** | Build only if searches without bookings are free under its terms (ticket F2). |
| Trip.com, Skyscanner, Expedia | — | **Do not scrape** | They block bots and their terms forbid it. |
| Amadeus Self-Service | — | **Not usable** | Decommissioned on 17 July 2026. |

### Context

| Source | What |
|---|---|
| `data/seeds/calendar_bd.csv` (hand-maintained) | Public holidays, Ramadan days, Eid ul-Fitr and Eid ul-Adha windows, Durga Puja, wedding season (roughly Nov–Feb), school holidays |
| GDELT DOC 2.0 API (free) | Daily article count and average tone per topic in `config/news_topics.yaml` |

### Fare grid (`config/routes.yaml`)

```yaml
origin: DAC
currency: BDT
country: BD
adults: 1
cabin: economy
trip_type: return
nights: 7
horizon_days: 120
depart_weekdays: [TUE, FRI]          # Google Flights grid
routes:
  - { destination: HAN, label: Hanoi }
  - { destination: BKK, label: Bangkok }
  - { destination: MNL, label: Manila }
  - { destination: VTE, label: Vientiane }
  # - { destination: SGN, label: Ho Chi Minh City }   # optional fifth
light_grid:                           # ShareTrip, GoZayaan
  depart_weekdays: [TUE]
  horizon_days: 90
```

About 4 routes × ~34 dates ≈ 140 Google Flights searches per run. The light grid is about 4 × 13 ≈ 52 per OTA.

---

## 7. Database schema

Postgres schemas: `raw`, `stg`, `ref`, `feat`, `pred`. `raw`, `stg` and `pred` are created by Alembic. `ref` and `feat` are built by dbt.

### Tables owned by Python (Alembic)

```sql
-- raw
raw.run_log (
  run_id uuid primary key,
  started_at timestamptz not null,
  finished_at timestamptz,
  status text,                         -- ok | partial | failed
  sources_ok text[],
  sources_failed text[],
  notes text
);

raw.fetch_log (
  id bigserial primary key,
  run_id uuid references raw.run_log,
  source text not null,
  url text,
  fetched_at timestamptz not null,
  http_status int,
  raw_path text,                       -- data/raw/...
  bytes int,
  error text
);

-- stg
stg.gold_observation (
  run_id uuid, observed_at timestamptz, source text,
  karat text check (karat in ('22K','21K','18K','traditional')),
  buy_bdt_per_gram numeric, sell_bdt_per_gram numeric,
  usd_bdt_used numeric, effective_date date,
  primary key (source, karat, effective_date, observed_at)
);

stg.fare_observation (
  run_id uuid, observed_at timestamptz, source text,
  origin text, destination text, depart_date date, return_date date,
  airline text, stops int, via text, duration_min int,
  price numeric, currency text, price_bdt numeric, fx_rate_used numeric,
  offer_key text,                      -- stable hash, see F4
  raw_offer jsonb
);

stg.xau_spot (date date primary key, usd_per_oz numeric, source text);
stg.fx_daily (date date, pair text, rate numeric, source text, primary key (date, pair));
stg.news_daily (date date, topic text, article_count int, avg_tone numeric,
                primary key (date, topic));

-- pred
pred.gold_next_change (as_of timestamptz, karat text, p_up numeric, p_down numeric,
                       expected_days_to_change numeric, rule_or_model text, model_version text);
pred.fare_signal (as_of timestamptz, origin text, destination text, depart_date date,
                  signal text check (signal in ('buy','wait')), p_drop_before_deadline numeric,
                  expected_low_bdt numeric, rule_or_model text, model_version text);
pred.outcome (prediction_table text, prediction_key text, resolved_at timestamptz,
              was_correct boolean, detail jsonb);
```

### Models owned by dbt

| Model | Grain | Key columns |
|---|---|---|
| `ref.calendar_bd` (seed) | date | holiday_name, is_public_holiday, ramadan_day, eid_window, puja_window, wedding_season |
| `stg.gold_change_event` (view) | BAJUS adjustment × karat | effective_at, karat, old_price, new_price, delta_bdt, delta_pct, direction |
| `stg.news_shock` (view) | day × topic | zscore over 90 days, shock_flag (z ≥ 3) |
| `feat.gold_daily` | day × karat | bajus_price, world_implied_price, premium_pct, days_since_change, xau_7d_pct, fx_7d_pct, holiday and shock flags |
| `feat.fare_daily` | day × route × depart_date | min_price_bdt, median_price_bdt, n_offers, days_to_departure, depart_dow, observed_dow, month, holiday_distance_days, price_percentile_vs_history, is_gap_day |
| `feat.run_calendar` | day | had_run, sources_ok_count |

---

## 8. KPIs and patterns (what the dashboard must show)

### Gold

- Current BAJUS price per karat, per gram and per bhori, buy and sell
- Change since the last adjustment, in taka and %
- Number of adjustments this month and this year, up vs down
- Average days between adjustments
- BAJUS premium over the world-implied price, with its 60-day band
- 30- and 90-day change and volatility

### Fares

- Cheapest live fare per route and departure date
- 7-day route minimum and median
- Today's fare percentile versus history at the same days-to-departure
- Days-to-departure price curve per route
- Day-of-week effect (departure day and observation day)
- Price gap between the Bangladeshi OTAs and Google Flights

### Pattern views (`dbt/models/analysis/`)

- **Weekday:** on which weekday does BAJUS announce? Which departure weekday is cheapest per route?
- **Season:** monthly fare level; gold demand in wedding season.
- **Occasions:** fare uplift in the 14 days before each Eid and Puja; do BAJUS changes cluster around budget day or festivals?
- **News event study:** average price move in the 7 days after a shock day versus a normal day.
- **Lag:** how many days does BAJUS trail world gold, and is it faster to follow rises than falls?

Gap days (`is_gap_day = true`) are **excluded** from weekday statistics.

---

## 9. Conventions for every ticket

1. **One ticket per session.** State the ticket ID in the first commit message (`G2: gold collector`).
2. **Every fetch goes through the shared client** (`tracker.core.fetch`). It handles rate limits, retries with backoff, the raw snapshot to `data/raw/<source>/<YYYY-MM-DD>/`, and a row in `raw.fetch_log`.
3. **One failing collector never stops the others.** The orchestrator catches the error, logs it, marks the run `partial` and continues.
4. **Parsers are pure functions** (`parse(raw_bytes) -> list[Row]`) tested on saved fixtures. No network in unit tests.
5. **Idempotent writes.** Re-running the same day must not duplicate rows (use primary keys and `ON CONFLICT DO NOTHING`).
6. **Config in YAML, secrets in `.env`.** Never hard-code URLs, routes or credentials.
7. **No ticket is done without** passing `make test`, `make lint`, and (where relevant) `dbt test`.
8. **Ask the owner before** adding a dependency, changing the schema of an existing table, or anything that could cost money or break a site's terms.
9. **Update `README.md`** whenever a new make target, env var or config file appears.

---

## 10. Makefile targets

| Target | Does |
|---|---|
| `make up` / `make down` | Start / stop Postgres and Metabase |
| `make migrate` | Run Alembic migrations |
| `make collect` | Full daily run: collectors → dbt run/test → predictions → alerts → backup → summary email |
| `make collect SOURCES=gold_goldr,fx_usd_bdt` | Run a subset (debugging) |
| `make backfill-gold` | One-off gold history backfill |
| `make reparse SOURCE=x SINCE=YYYY-MM-DD` | Re-parse stored raw snapshots into `stg` |
| `make dbt` | `dbt run && dbt test` |
| `make backtest` | Run backtests for all rules and models |
| `make backup` / `make restore FILE=...` | `pg_dump` / restore into the running Postgres |
| `make test` / `make lint` | pytest / ruff |

---

## 11. Tickets

Gold comes first: it has history from day one, so it gives quick wins while fare data accumulates.

### Phase 0 — Foundation

#### T0.1 Repo scaffold
- **Do:** Create the layout in §4. Set up `pyproject.toml` with uv, ruff config, pytest config, `.gitignore` (`.env`, `data/raw/`, `backups/`), `.env.example`, Makefile skeleton, and a GitHub Actions workflow running lint and tests.
- **Done when:** `make lint` and `make test` pass locally and in CI on an empty test.

#### T0.2 Docker Compose and database
- **Do:** Write `docker-compose.yml` with services `postgres` (16, named volume, healthcheck), `metabase` (port 3000, its own app DB on a volume) and `collector` (built from `Dockerfile` with Python 3.12 and Playwright Chromium, `profiles: [run]` so it only starts on demand). Add Alembic with an initial migration creating the schemas and the tables in §7.
- **Done when:** `make up && make migrate` works from a clean clone, and Metabase can connect to Postgres.

#### T0.3 Core library and orchestrator
- **Do:** Build `tracker.core`:
  - `settings` (pydantic-settings)
  - `db` (engine, upsert helpers)
  - `fetch` (httpx client: per-domain rate limit from `sources.yaml`, 3 retries with exponential backoff, honest user agent, raw gzip save, `fetch_log` row)
  - `runlog` (creates `run_id`, writes `raw.run_log`)
  - `units` (Bengali numerals, gram/bhori/ana/rati conversions)
  - `email` (Gmail SMTP sender)

  Then write `orchestrator.py`: create the run, call enabled collectors in order (each wrapped in try/except), then dbt, scoring and alerts, then finish the run and email a summary of sources OK/failed, row counts and alerts fired.
- **Done when:** with a dummy collector, `make collect` writes one `run_log` row and one `fetch_log` row, saves a raw file and sends a summary email. Unit tests cover retries, the numeral converter and unit conversions.

#### T0.4 Backups
- **Do:** At the end of each run, `pg_dump -Fc` to `backups/daily/`. Keep the last 14 daily dumps and promote one per week to `backups/weekly/` (keep 8). Add `make restore`.
- **Done when:** restoring a dump into a fresh container reproduces the row counts.

### Phase 1 — Gold

#### G1 Find goldr's data feed
- **Do:** Inspect `price.ultra.js`, `widget.js` and `price.js`, and the network requests on goldr pages, to find the JSON or CSV endpoint(s) for current and historical prices. Write findings to `docs/sources/goldr.md`: URLs, fields, units, update time, and any terms on reuse. If no feed exists, implement an HTML parser for the home page tables (per-gram table) using the numeral helper.
- **Done when:** the findings note exists and a parser test passes on a saved fixture.

#### G2 Gold collector
- **Do:** `gold_goldr.py` fetches current prices and writes one row per karat to `stg.gold_observation`, with buy, sell, USD rate used and BAJUS effective date (if shown).
- **Done when:** a real run lands 4 rows. Re-running the same day adds no duplicates.

#### G3 Backfill and gap-fill
- **Do:** `gold_goldr_history.py` loads at least 2 years of history once (`make backfill-gold`). On every normal run, it fills any dates since the last successful gold observation.
- **Done when:** history is loaded and spot-checked against 5 known announcements (document them in the test). After skipping a day, the next run fills it.

#### G4 BAJUS cross-check
- **Do:** Fetch the BAJUS official price and compare it with goldr for 22K per gram.
- **Done when:** a mismatch over ৳1 is listed in the run email. If goldr fails, BAJUS rows are used instead (`source = 'bajus'`).

#### G5 World gold and FX
- **Do:** `xau_spot.py` (daily close, from a free source; start with goldr's spot page) and `fx_usd_bdt.py` (Bangladesh Bank reference rate), each with history backfill.
- **Done when:** both tables are continuous over the gold backfill period, apart from documented market holidays.

#### G6 dbt gold models
- **Do:** Set up the dbt project and seed `calendar_bd.csv` (see C1 for content; a stub is fine here). Build `stg.gold_change_event` and `feat.gold_daily` (§7), with tests for not-null, uniqueness and accepted values.
- **Done when:** `dbt test` passes and every real BAJUS adjustment in the backfill appears exactly once as a change event.

#### G7 Gold change alert
- **Do:** When a run detects a new change event, email old → new price, delta (৳ and %), and the current premium versus world.
- **Done when:** a seeded test change triggers exactly one email. Re-running does not re-send it (track sent alerts).

### Phase 2 — Fares

#### F1 Google Flights collector
- **Do:** Load `routes.yaml`, build the date grid, and query via the unofficial client behind a `FareSource` interface (`search(origin, dest, depart, ret) -> list[Offer]`). Use country BD and currency BDT. Randomise order, add 2–5 s jitter between searches, and stop the source after 5 consecutive errors.
- **Done when:** a full grid (~140 searches) completes in one run. Offers land in `stg.fare_observation` with `raw_offer` JSON kept.

#### F2 Duffel decision
- **Do:** Read Duffel's current pricing and terms. Decide whether searches without bookings are free for this usage. Write the decision and evidence to `docs/sources/duffel.md`.
- **Done when:** the decision is written down. Only if it is free: implement `fares_duffel.py` behind `FareSource`, disabled by default in `sources.yaml`.

#### F3 ShareTrip and GoZayaan
- **Do:** Playwright collectors for the light grid. On any parse failure, save a full-page screenshot next to the raw HTML. Use one browser context per run and close it cleanly.
- **Done when:** taka prices land for the light grid from both sites. Fixture tests pass on saved result pages.

#### F4 Normalisation
- **Do:** Convert to BDT using `stg.fx_daily` (store `fx_rate_used`). Define `offer_key = sha1(origin|dest|depart|return|airline|flight numbers|stops)`. Deduplicate the same offer seen twice in one run.
- **Done when:** the same flight from two sources shares one `offer_key` in a test.

#### F5 dbt fare models
- **Do:** Build `feat.fare_daily` and `feat.run_calendar`. Compute `price_percentile_vs_history` per route at the same days-to-departure bucket (0–13, 14–30, 31–45, 46–60, 61–90, 91+). Mark `is_gap_day` for days with no run.
- **Done when:** `dbt test` passes, and gap days are marked, never filled.

#### F6 Watched trips
- **Do:** `config/watched_trips.yaml` (example below). Email when the cheapest matching fare falls below `target_bdt`, or drops at least 5% since the last run.
- **Done when:** a seeded test drop triggers one email, and no repeat for the same drop.

```yaml
- name: Laos autumn 2027
  origin: DAC
  destination: VTE
  depart_between: [2027-10-24, 2027-11-15]
  nights: 6-8
  target_bdt: 50000
```

### Phase 3 — Context

#### C1 Calendar seed
- **Do:** Fill `data/seeds/calendar_bd.csv` for 2023–2027 with public holidays, Ramadan start/end, Eid ul-Fitr and Eid ul-Adha (use the **announced** dates; mark future ones as `estimated`), Durga Puja, wedding season and school holidays.
- **Done when:** the seed loads and `estimated` dates are clearly flagged.

#### C2 GDELT news
- **Do:** `news_gdelt.py` queries GDELT DOC 2.0 daily for the topics in `config/news_topics.yaml` (gold, Federal Reserve, war/conflict, oil, Bangladesh politics, aviation/airports). Store count and average tone. dbt computes the z-score and `shock_flag`.
- **Done when:** a spot check shows shock days matching known major news days.

### Phase 4 — Analytics

#### A1 Metabase dashboards
- **Do:** Three dashboards: **Gold**, **Fares**, **Patterns**, covering every KPI in §8. Export the definitions as JSON to `dashboards/`.
- **Done when:** they open at `http://localhost:3000` and every KPI in §8 is visible.

#### A2 Pattern views
- **Do:** dbt analysis models for each pattern in §8.
- **Done when:** each returns results on the backfilled gold data (fare patterns will be sparse at first, which is expected).

#### A3 Weekly digest
- **Do:** The first run on or after each Friday emails a digest: the week's BAJUS changes, fare moves per route, current signals, and missed days.
- **Done when:** one digest per week, never two.

### Phase 5 — Prediction

#### P1 Gold rule and backtest harness
- **Rule:** signal a change within 7 days when `premium_pct` drifts outside its 60-day mean ± k·sd. Direction = sign of the drift.
- **Harness:** a walk-forward backtest over the backfill. Report hit rate, precision/recall for "change within 7 days", directional accuracy and average lead time. Tune `k` on the first 70% of the backfill, evaluate on the last 30%.
- **Done when:** `make backtest` prints the report, and predictions are written daily to `pred.gold_next_change`.

#### P2 Gold model
- **Do:** A LightGBM classifier on `feat.gold_daily` features, with the same walk-forward split.
- **Done when:** it **ships only if it beats P1** on the held-out period. Otherwise, document why and keep the rule.

#### P3 Fare rule and backtest
- **Rule:** `buy` if today's fare is in the cheapest 25% seen at the same days-to-departure bucket for that route, otherwise `wait`.
- **Harness:** simulated money saved versus "always buy now".
- **Done when:** the report covers each route once there are at least 8 weeks of data.

#### P4 Fare model
- **Do:** A LightGBM classifier for "drops ≥5% before 14 days out".
- **Done when:** it ships only if it beats P3. Start this no earlier than 8–12 weeks after F1 goes live.

#### P5 Prediction scorecard
- **Do:** Every prediction is resolved into `pred.outcome` once its outcome is known, and the dashboard shows a rolling accuracy.
- **Done when:** the scorecard shows on the Patterns dashboard.

---

## 12. Risks and how the code should handle them

| Risk | Handling |
|---|---|
| A site changes its HTML | Raw snapshots kept; parse failure listed in the run email; fixture tests; `make reparse` after the fix |
| The unofficial Google Flights client breaks | It sits behind `FareSource`; the OTAs keep collecting; swap the implementation |
| Blocked by a site | Log it, skip the source for this run, report it in the email. **Never** evade blocks. |
| Missed days | Gold is gap-filled; fare gaps are flagged and excluded from weekday statistics |
| Disk or laptop failure | Backups after every run; the owner copies `backups/weekly/` off the machine |
| goldr disappears | BAJUS official site as fallback (G4) |
| Eid dates shift with the moon | Editable CSV with an `estimated` flag |
| Overfitting on little data | Rules first; models must beat rules in walk-forward backtests |

---

## 13. Environment variables (`.env.example`)

```
POSTGRES_USER=tracker
POSTGRES_PASSWORD=change-me
POSTGRES_DB=tracker
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
ALERT_TO=you@gmail.com

TZ_DISPLAY=Asia/Dhaka
DUFFEL_API_TOKEN=            # only if F2 approves Duffel
```

---

## 14. Definition of done for v1

- [ ] `make collect` runs end to end in a few minutes and sends a summary email
- [ ] At least 2 years of BAJUS history loaded, with change events correct
- [ ] Daily fares for 4 routes from Google Flights plus the two Bangladeshi OTAs
- [ ] Metabase shows every KPI in §8
- [ ] BAJUS change and watched-trip alerts arrive by email
- [ ] Gold rule (P1) running with a backtest report
- [ ] Backups verified with a test restore
