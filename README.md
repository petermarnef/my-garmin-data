# my-garmin-data

Two scripts to pull health and training data from Garmin Connect and consolidate it into a single compact file for analysis. Syncs sleep, heart rate, HRV, stress, body battery, hydration, nutrition (requires Connect+), activities, body composition, lifestyle logging, and more.

Works on macOS, Linux, and Windows.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (a fast Python package runner):

```bash
# macOS
brew install uv

# Linux / Windows
curl -LsSf https://astral.sh/uv/install.sh | sh
```

That's it — no virtual environment or `pip install` needed. `uv` reads the dependency metadata embedded in the scripts and handles everything automatically.

## Usage

```bash
uv run sync_garmin_data.py
uv run consolidate_garmin_data.py
```

<details>
<summary>Alternative: manual venv setup (without uv)</summary>

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python sync_garmin_data.py
.venv/bin/python consolidate_garmin_data.py

# Windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python sync_garmin_data.py
.venv\Scripts\python consolidate_garmin_data.py
```

</details>

On first run, the sync script pulls up to 365 days of history. After that, it only fetches new data since the last sync. The last 2 days are always refreshed to catch late-arriving data (hydration, body composition, lifestyle logging). If a new data type is added to the script, it automatically backfills existing days on the next run.

## What data is synced

The sync script pulls the following from Garmin Connect per day:

- **Daily summary** — steps, distance, floors, calories, activity levels, heart rate
- **Sleep** — duration breakdown (deep/light/REM/awake), sleep score, stress, respiration, skin temp
- **Heart rate** — resting, min, max
- **HRV** — weekly average, nightly average, status
- **Stress** — all-day average and max
- **Body battery** — high, low, charged, drained
- **Respiration** — waking and sleep averages
- **SpO2** — blood oxygen saturation
- **Training readiness** — score, level, recovery time
- **Hydration** — fluid intake, goal, sweat loss
- **Intensity minutes** — moderate and vigorous
- **Lifestyle logging** — custom tracked items (e.g. Alcohol, Illness, Matcha) with YES/NO status
- **Floors and steps** — detailed daily data

Plus these non-daily datasets:

- **Activities** — full detail for every recorded workout/activity
- **Body composition** — weight, BMI, body fat %, body water %, bone mass, muscle mass
- **Nutrition** — individual food items per meal with full macros (requires [Garmin Connect+](https://www.garmin.com/connectplus/) subscription)
- **Personal records** — fastest 1K/5K/10K, longest run/ride, etc.
- **Weekly trends** — step and stress aggregates
- **Profile** — gender, age, height, VO2max, devices

## Reliability features

- **Incremental sync** — only fetches new data since last run
- **Late-data refresh** — last 2 days are always re-fetched (hydration, body comp, and lifestyle logging can arrive late)
- **Automatic backfill** — missing files for existing days are detected and fetched
- **Rate limiting** — 1 second delay between API calls, exponential backoff on 429 errors (up to 3 retries)
- **Failure tracking** — failed API calls are logged per date/type and summarized at the end
- **Non-interactive mode** — fails fast with a clear message when tokens expire in cron/scheduled runs (instead of hanging on a login prompt)
- **Atomic CSV write** — consolidation writes to a temp file first, then renames, preventing corrupt output on crash

## Authentication

Your email and password are **not stored by the scripts**. They are only used at login to authenticate with Garmin Connect, which returns API tokens. Those tokens are saved to `~/.garminconnect` in your home folder and reused on subsequent runs. If they expire, you'll be prompted to log in again. You can optionally pass credentials via `EMAIL` and `PASSWORD` environment variables instead of the interactive prompt.

## Output

After running both scripts, the summary file is at:

```
~/garmin_data/claude_summary/garmin_data.csv
```

The file is self-documenting with a comment header explaining every column, scale, and section. It contains:

1. **PROFILE** — gender, birth date, height, weight, VO2max, lactate threshold HR
2. **DAILY_METRICS** — one row per day (~52 columns)
3. **BODY_COMPOSITION** — one row per weigh-in
4. **ACTIVITIES** — one row per activity (~24 columns)
5. **NUTRITION_DAILY** — one row per day with total macros (Connect+ only)
6. **NUTRITION_ITEMS** — one row per food item logged, with meal, brand, serving, and full macros (Connect+ only)
7. **PERSONAL_RECORDS** — best performances

## Analyzing your data with AI

The easiest way to get started is to point your AI (ChatGPT, Claude, Gemini, etc.) to [CLAUDE.md](CLAUDE.md) before asking questions. It describes every data file, section, column, and scale — giving the AI all the context it needs to analyze your data without back-and-forth.

The summary file itself (`~/garmin_data/claude_summary/garmin_data.csv`) is also self-documenting with inline comment headers, so uploading it on its own works too.

## Credits

Built on top of [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) by cyberjunky.

Co-developed with [Claude](https://claude.ai) (Opus 4.6) by Anthropic.
