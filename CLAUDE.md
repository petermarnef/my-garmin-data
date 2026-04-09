# Garmin Connect Python Project

## What This Is

Two scripts for syncing health data from Garmin Connect and consolidating it into a single file for analysis. Built on the [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) library.

## How to get fresh data and update the summary

```bash
cd ~/dev/my-garmin-data && uv run sync_garmin_data.py && uv run consolidate_garmin_data.py
```

**What happens:**

1. `sync_garmin_data.py` pulls raw JSON from Garmin Connect into `~/garmin_data/`. Only fetches what doesn't exist locally. Automatically backfills missing files for existing days. Last 2 days are always refreshed (late-arriving data). If tokens (`~/.garminconnect`) are expired, prompts for email, password, and MFA (fails fast in non-interactive mode).
2. `consolidate_garmin_data.py` reads all raw JSON and produces one summary file at `~/garmin_data/claude_summary/garmin_data.csv`. Incremental — only processes new days/activities. Original data is never modified. Writes atomically via temp file.

## What data is synced

**Per day** (14 JSON files per day + nutrition):
- Daily summary (steps, distance, floors, calories, activity levels, heart rate)
- Sleep (duration breakdown, score, stress, respiration, skin temp)
- Heart rate (resting, min, max)
- HRV (weekly avg, nightly avg, status)
- Stress (all-day average and max)
- Body battery (high, low, charged, drained)
- Respiration (waking and sleep averages)
- SpO2 (blood oxygen)
- Training readiness (score, level, recovery time)
- Hydration (fluid intake, goal, sweat loss)
- Intensity minutes (moderate, vigorous)
- Lifestyle logging (custom tracked items like Alcohol, Illness, Matcha with YES/NO)
- Floors and steps detail
- Nutrition — individual food items per meal with full macros (requires Connect+)

**Non-daily:**
- Activities (full detail per workout)
- Body composition (weight, BMI, body fat %, body water %, bone/muscle mass)
- Personal records (fastest 1K/5K/10K, longest run/ride, etc.)
- Weekly trends (steps, stress)
- Profile (gender, age, height, VO2max, devices)

## How to ask Claude about the data

Point Claude to this single file:

```
~/garmin_data/claude_summary/garmin_data.csv
```

The file is self-documenting — it has a comment header at the top explaining every column, every scale, and every section. It contains:

1. **PROFILE** — gender, birth date, height, weight, VO2max, lactate threshold HR
2. **DAILY_METRICS** — one row per day (~52 columns): steps, sleep breakdown, HRV, stress, body battery, training readiness, hydration, lifestyle logging, respiration, SpO2
3. **BODY_COMPOSITION** — one row per weigh-in: weight (kg), BMI, body fat %, body water %, bone mass, muscle mass
4. **ACTIVITIES** — one row per activity (~24 columns): type, duration, HR, training effect, training load, power, cadence, elevation, body battery impact
5. **NUTRITION_DAILY** — one row per day with total macros: calories, protein, carbs, fat, fiber, sugar, saturated fat, sodium, item count (Connect+ only)
6. **NUTRITION_ITEMS** — one row per food item: meal, food name, brand, serving size/qty, full macros (Connect+ only)
7. **PERSONAL_RECORDS** — best performances (fastest 1K/5K, longest run/ride, etc.)

Only go to the raw JSON files in `~/garmin_data/daily/` or `~/garmin_data/activities/` if granular intra-day or per-activity detail is needed beyond what the summary provides.

## Data locations

| Path | Contents |
| --- | --- |
| `~/garmin_data/daily/{YYYY-MM-DD}/` | 14 JSON files per day (summary, sleep, hrv, stress, lifestyle logging, etc.) |
| `~/garmin_data/activities/` | One JSON file per activity (by activity ID) |
| `~/garmin_data/body_composition/` | Body comp and weigh-in data |
| `~/garmin_data/nutrition/{YYYY-MM-DD}/` | Food log JSON per day (Connect+ only) |
| `~/garmin_data/weekly/` | Weekly step/stress trends (not in summary — derivable from daily data) |
| `~/garmin_data/profile/` | User profile and devices |
| `~/garmin_data/personal_records.json` | Personal bests |
| `~/garmin_data/claude_summary/garmin_data.csv` | **The single file to read for analysis** |
| `~/garmin_data/claude_summary/processing_state.json` | Tracks which dates and activities have been consolidated |
| `~/garmin_data/sync_state.json` | Tracks last sync date for incremental pulls |

## Sync behavior

- **Incremental**: only fetches data since last sync (or 365 days on first run)
- **Late-data refresh**: last 2 days always re-fetched (hydration, body comp, lifestyle logging arrive late)
- **Backfill**: missing files for existing days are automatically detected and fetched
- **Rate limiting**: 1s delay between calls, exponential backoff on 429 errors (3 retries max)
- **Failure tracking**: failed API calls logged per date/type, summary printed at end
- **Non-interactive guard**: fails fast with clear message when tokens expire in cron/automated runs
- **Atomic write**: consolidated CSV written via temp file + rename to prevent corruption
