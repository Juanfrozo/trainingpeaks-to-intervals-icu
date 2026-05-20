# TrainingPeaks → intervals.icu Sync

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Mirror your **planned** workouts, races, rest days, and coach notes from TrainingPeaks to intervals.icu — with full structured power, pace, and heart-rate targets converted to absolute values, so the AI on intervals.icu (and the workout pushed to your Garmin / Wahoo) actually understands what your coach planned.

A standalone Python CLI. **Activities from Garmin / Rouvy / Wahoo continue to sync directly to intervals.icu as before** — this tool only fills the missing direction (TP plan → icu plan) plus a couple of niceties around it.

---

## Why this exists

If your setup is **TrainingPeaks for the coach-written plan + intervals.icu for AI analysis + Garmin/Rouvy for recording**, you have one missing link: intervals.icu has no idea what was planned. Auto-pairing on icu matches activities with planned events by date and sport — so the moment the plan lives in icu too, the AI / Form chart / PMC / Performance Power Profile all become a lot more useful.

## What it syncs

| TrainingPeaks side | becomes on intervals.icu |
|---|---|
| Planned workout (Bike / Run / Swim / MTB / Strength / …) | `WORKOUT` event with sport-correct type |
| Structured intervals (`%FTP`, `%LTHR`, `%threshold pace`) | `workout_doc` with **absolute** watts / bpm / s/km, computed from **your TP thresholds** |
| Workout `description` (coach text) | event description (+ pushed into paired `activity.description`) |
| `coachComments` | "Coach:" section in description |
| `workoutComments` (threaded) | "Comments:" bullet list in description |
| `Day Off`, `Reisetag`, content-less workouts | `NOTE` event (no sport, no TSS) |
| `Race` workouts | `RACE_A` event (counts properly in PMC) |
| Workout deleted from TP | event deleted from icu (only if originally synced by us) |

After the event sync, the script also rewrites paired `activity.description` to the TP coach text, so your **completed** workouts in icu carry the coach's notes too.

## What it does **not** do

- No `.fit` upload / activity sync from TP — Garmin / Rouvy / Wahoo already do that directly to intervals.icu
- No wellness, ATP, fitness chart, library, or settings push
- No bidirectional sync — TP is the source of truth

## Sport mapping

| TrainingPeaks | intervals.icu |
|---|---|
| Swim (1) | Swim |
| Bike (2), Time Trial (47), Road / Gravel / Track / Cyclocross | Ride |
| Run (3), Road / Track / Trail Run | Run |
| Indoor / Virtual Bike (6, 49) | VirtualRide |
| Indoor / Virtual Run (13, 50) | VirtualRun |
| Mountain Bike (8) + all MTB subtypes | MountainBikeRide |
| Walk (13), Treadmill Walk | Walk |
| Hike (41), Mountaineering, Hunting | Hike |
| Strength (9 / 29) | WeightTraining |
| XC-Ski (11) | NordicSki |
| Rowing (12), Indoor Rowing, Virtual Rowing | Rowing |
| Race (6) | category `RACE_A` (sport from subtype, default `Run`) |
| Day Off (7) / empty workouts | category `NOTE` |
| Anything else | Workout |

## Requirements

- Python **3.10** or newer
- A **TrainingPeaks** account (any plan — uses cookie-based auth, no API approval required)
- An **intervals.icu** account with **Developer Settings** API key enabled

## Install

**Recommended — install globally with [uv](https://github.com/astral-sh/uv):**

```bash
git clone https://github.com/Sladck/trainingpeaks-to-intervals-icu.git
uv tool install ./trainingpeaks-to-intervals-icu
```

This puts `tp-icu-sync` on your `PATH` (typically `~/.local/bin/tp-icu-sync`), in its own isolated venv. You can call it from any directory.

**Alternative — pipx:**

```bash
pipx install ./trainingpeaks-to-intervals-icu
```

**Alternative — local venv:**

```bash
git clone https://github.com/Sladck/trainingpeaks-to-intervals-icu.git
cd trainingpeaks-to-intervals-icu
python3 -m venv .venv
.venv/bin/pip install -e .
# invoke as .venv/bin/tp-icu-sync ...
```

## Get your credentials

### TrainingPeaks cookie (expires when you log out)

1. Open <https://www.trainingpeaks.com> in a browser, log in
2. DevTools → Application → Cookies → `https://www.trainingpeaks.com`
3. Copy the value of the `Production_tpAuth` cookie (a long base64-like string)

### intervals.icu API key

1. <https://intervals.icu/settings> → "Developer Settings"
2. Enable API access, copy the key

### intervals.icu athlete ID

1. Open your profile page on intervals.icu — the URL contains your athlete id, e.g. `https://intervals.icu/athlete/i123456`
2. Copy `i123456` (with the `i` prefix)

## Configure

The CLI looks for a `.env` file in this order (first hit wins):

1. `./.env` in current directory
2. `$XDG_CONFIG_HOME/tp-icu-sync/.env` — defaults to `~/.config/tp-icu-sync/.env` — **recommended for a global install**
3. `~/.tp-icu-sync.env`

You can also pass `--env-file PATH` or simply export the three variables in your shell.

```bash
mkdir -p ~/.config/tp-icu-sync
cp trainingpeaks-to-intervals-icu/.env.example ~/.config/tp-icu-sync/.env
chmod 600 ~/.config/tp-icu-sync/.env
$EDITOR ~/.config/tp-icu-sync/.env
```

```dotenv
TP_AUTH_COOKIE=V001...long string...
ICU_API_KEY=...your key...
ICU_ATHLETE_ID=i123456
```

## Usage

```bash
tp-icu-sync --dry-run              # show diff, write nothing
tp-icu-sync                        # actually apply
tp-icu-sync --days 30              # plan window: 30 days forward
tp-icu-sync --activity-lookback 0  # disable activity-description sync
tp-icu-sync --env-file ./other.env # use a different .env
tp-icu-sync -v                     # debug logs (HTTP calls etc.)
```

Run manually whenever you change your plan in TrainingPeaks. Or wrap it in cron / systemd-timer / launchd for set-and-forget.

### Example output

```
INFO  Using env file: /Users/alice/.config/tp-icu-sync/.env
INFO  Fetching athlete thresholds
INFO    thresholds: FTP=250 W, LTHR=167 bpm, run_pace=252 s/km, swim_pace=98 s/100m
INFO  Fetching TP planned workouts 2026-05-20..2026-06-03
INFO    TP returned 14 planned workout(s)
INFO  Fetching icu events 2026-05-20..2026-06-03
INFO    icu returned 13 total event(s), 13 previously synced by us
INFO  + create 2026-05-26 [NOTE] Reisetag
INFO  ~ update 2026-05-21 [Ride] 2x15min medium
INFO  + activity desc 2026-05-17 [Run] Glonn Laufen (id=i149116742)

[APPLIED] created=1 updated=1 deleted=0 unchanged=12 activity_desc=1
```

## How it stays consistent

Each event we create on icu gets:

- `external_id = "tp:<workoutId>"` — to identify our events on the next run
- A `[tp-sync hash=<12 hex>]` footer in `description` — a content hash that drives the diff (create / update / unchanged / delete)

We **only ever touch events that carry our `tp:` prefix**. Anything you created manually on intervals.icu, anything from another integration, and all activities from your devices stay strictly untouched.

A workout that disappears from TP in the sync window is deleted from icu — but only if it has our prefix, so deletion is safe.

## CLI reference

```
usage: tp-icu-sync [-h] [--days DAYS] [--activity-lookback ACTIVITY_LOOKBACK]
                   [--env-file ENV_FILE] [--dry-run] [-v]

Mirror planned TrainingPeaks workouts to intervals.icu calendar.

options:
  --days DAYS                          Rolling window in days from today (default: 14)
  --activity-lookback ACTIVITY_LOOKBACK Look this many days back for paired-activity desc sync (default: 14, 0 disables)
  --env-file ENV_FILE                  Path to a .env file
  --dry-run                            Show what would change, write nothing
  -v, --verbose                        DEBUG-level logging
```

## Project layout

```
src/tp_icu_sync/
├── cli.py                     # argparse entry point
├── config.py                  # .env discovery + load
├── sync.py                    # diff + apply orchestration (events & activities)
├── tp/{client,api,models}.py  # TrainingPeaks API wrapper (cookie -> token)
├── icu/{client,api,models}.py # intervals.icu API wrapper (Basic Auth)
└── mapping/
    ├── sport.py               # workoutTypeValueId -> icu sport type
    └── structure.py           # TP structure -> icu workout_doc + human-readable text
```

## Troubleshooting

**`AUTH ERROR: TrainingPeaks cookie expired or invalid`**
Your TP session ended. Log out + back in at trainingpeaks.com, grab a fresh `Production_tpAuth` cookie, update `.env`.

**`AUTH ERROR: intervals.icu auth failed (HTTP 401)`**
API key wrong or rotated in icu Developer Settings.

**A pace target shows as `% pace` instead of `mm:ss/km`**
Your TrainingPeaks athlete settings have no run / swim threshold pace defined. Set it in TP under Athlete Settings → Pace Zones, re-run sync.

**A workout has no `workout_doc` after sync**
The coach wrote it as plain text in TP with no machine-readable structure. We can't synthesize intervals from prose, so only the description gets pushed. That's intentional.

**A race shows up as Run but it's a Bike race**
TP didn't include a subtype, so we defaulted to Run. Change the `type` on the event in intervals.icu and the next sync will keep your override (we only touch fields we own).

## Credits / inspiration

The cookie → OAuth token exchange flow used to talk to TrainingPeaks was studied from [JamsusMaximus/trainingpeaks-mcp](https://github.com/JamsusMaximus/trainingpeaks-mcp). This project doesn't import or depend on that codebase — the pattern was reimplemented standalone.

## License

[MIT](./LICENSE)
