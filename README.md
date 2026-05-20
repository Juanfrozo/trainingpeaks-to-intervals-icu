# TrainingPeaks → intervals.icu sync

Mirror planned workouts from TrainingPeaks to your intervals.icu calendar — including structured power, pace, and heart-rate targets — so intervals.icu has the plan alongside the activities your devices upload.

This is a **standalone Python CLI**. It does not depend on any other library or MCP server, and it doesn't replace the existing Garmin/Rouvy → intervals.icu activity flow — it only fills in the missing direction (TP plan → icu plan).

## What it does

- Pulls planned workouts from TrainingPeaks for a rolling window (default 14 days forward)
- Creates / updates / deletes matching events on intervals.icu under the `WORKOUT` category
- Converts TP percent-of-threshold targets (`%FTP`, `%LTHR`, `%threshold pace`) into **absolute values** using your TP thresholds — so intervals.icu shows real watts, bpm, and min/km, and Garmin/Wahoo get a real workout structure pushed to the watch
- After the event sync, pushes the TP description into paired icu **activities** as well, so completed workouts carry the coach's notes
- Idempotent: a re-run with no TP changes performs 0 writes
- Source of truth is TrainingPeaks: a workout that disappears from TP is also deleted from intervals.icu (only events tagged with our `tp:<id>` external_id are eligible — your manually created icu events and your devices' activities are never touched)

## What it does **not** do

- No activity upload from TP to icu (Garmin / Rouvy / Wahoo already sync activities directly to intervals.icu, and intervals.icu auto-pairs them with our planned events by date + sport)
- No wellness data, ATP, fitness chart, or library import
- No interactive coach feedback / comments propagation

## Sport mapping

| TrainingPeaks | intervals.icu |
|---|---|
| Swim (1) | Swim |
| Bike (2) | Ride |
| Run (3) | Run |
| Mountain Bike (8) | MountainBikeRide |
| Strength (9 / 29) | WeightTraining |
| XC-Ski (11) | NordicSki |
| Rowing (12) | Rowing |
| Walk (13) | Walk |
| Subtype: Indoor / Virtual Bike (6, 49) | VirtualRide |
| Subtype: Indoor / Virtual Run (13, 50) | VirtualRun |
| Subtype: Hike (41) | Hike |
| Anything else | Workout |

## Requirements

- Python 3.10 or newer
- A TrainingPeaks account (any plan — uses cookie-based auth, no API approval needed)
- An intervals.icu account with the **Developer Settings** API key enabled

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/Sladck/trainingpeaks-to-intervals-icu.git
cd trainingpeaks-to-intervals-icu

# With uv (recommended)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .

# Or with stdlib venv + pip
python3 -m venv .venv
.venv/bin/pip install -e .
```

### 2. Get your credentials

**TrainingPeaks cookie** (expires when you log out):

1. Open https://www.trainingpeaks.com in a browser and log in
2. Open browser DevTools → Application / Storage → Cookies → `https://www.trainingpeaks.com`
3. Copy the value of the `Production_tpAuth` cookie (long base64-ish string)

**intervals.icu API key:**

1. Go to https://intervals.icu/settings → "Developer Settings"
2. Enable API access, copy the API key

**intervals.icu athlete ID:**

1. Open your profile page on intervals.icu — the URL contains your athlete id, e.g. `https://intervals.icu/athlete/i123456`
2. Copy `i123456` (with the `i` prefix)

### 3. Configure environment

```bash
cp .env.example .env
$EDITOR .env
```

Fill in the three values:

```
TP_AUTH_COOKIE=V001...long string...
ICU_API_KEY=...your key...
ICU_ATHLETE_ID=i123456
```

`.env` is in `.gitignore` and will not be committed.

## Usage

```bash
.venv/bin/tp-icu-sync --dry-run        # show diff, write nothing
.venv/bin/tp-icu-sync                   # actually apply
.venv/bin/tp-icu-sync --days 30         # bigger plan window
.venv/bin/tp-icu-sync --activity-lookback 0  # disable activity-description sync
.venv/bin/tp-icu-sync -v                # verbose / debug logs
```

Or after `source .venv/bin/activate`:

```bash
tp-icu-sync --dry-run
```

Run it manually whenever you change your plan in TrainingPeaks (or schedule it via cron / systemd-timer).

### Example output

```
INFO    Fetching athlete thresholds
INFO      thresholds: FTP=250 W, LTHR=167 bpm, run_pace=252 s/km, swim_pace=98 s/100m
INFO    Fetching TP planned workouts 2026-05-20..2026-06-03
INFO      TP returned 13 planned workout(s)
INFO    Fetching icu events 2026-05-20..2026-06-03
INFO      icu returned 13 total event(s), 13 previously synced by us
INFO    + create 2026-05-22 [Ride] Sweet Spot 3x12

[APPLIED] created=1 updated=0 deleted=0 unchanged=12 activity_desc=0
```

## How it stays consistent

Each icu event we create gets:

- `external_id="tp:<workoutId>"` — used to identify our events across runs and to know what to update vs leave alone
- A `[tp-sync hash=<12 hex>]` footer in `description` — a content hash that we compare on the next run to decide create/update/unchanged

We **only ever touch icu events that carry our `external_id` prefix**. Anything you created manually in intervals.icu, anything imported from another tool, and all activities from Garmin/Rouvy/Wahoo are left strictly alone.

A workout that disappears from TrainingPeaks within the sync window is deleted from intervals.icu — but only if it has our prefix (so deletion is safe).

## Project layout

```
src/tp_icu_sync/
├── cli.py                   # argparse entry point
├── config.py                # .env loader
├── sync.py                  # diff + apply orchestration
├── tp/{client,api,models}.py# TrainingPeaks API wrapper
├── icu/{client,api,models}.py # intervals.icu API wrapper
└── mapping/
    ├── sport.py             # workoutTypeValueId -> icu type
    └── structure.py         # TP structure -> icu workout_doc + human text
```

## Troubleshooting

**`AUTH ERROR: TrainingPeaks cookie expired or invalid`**
Your TP session expired. Log out and back in at trainingpeaks.com, grab the new `Production_tpAuth` cookie, update `.env`.

**`AUTH ERROR: intervals.icu auth failed (HTTP 401)`**
API key wrong, or the key was rotated in icu Developer Settings.

**A workout doesn't get a structured `workout_doc`**
TrainingPeaks workouts that the coach wrote as plain text (no machine-readable structure) have only a `description`. We can't synthesize structure from prose, so only the description gets pushed. That is intentional.

**A `pace` target shows as `% pace` in icu instead of mm:ss/km**
Your TrainingPeaks athlete settings have no run/swim speed threshold defined. Set your threshold pace in TP under Athlete Settings → Pace Zones, then re-run the sync.

## Inspiration

The cookie → OAuth token exchange used to talk to TrainingPeaks was inspired by [JamsusMaximus/trainingpeaks-mcp](https://github.com/JamsusMaximus/trainingpeaks-mcp). This project does not import or depend on that codebase — only the auth pattern was studied and reimplemented.

## License

[MIT](./LICENSE)
