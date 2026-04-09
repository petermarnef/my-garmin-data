#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["garminconnect>=0.2.38", "garth>=0.5.17", "requests>=2.0"]
# ///
"""Garmin Connect Data Sync Script.

Pulls health/fitness data from Garmin Connect and stores it locally
in ~/garmin_data/ as organized JSON files.

First run: pulls 365 days of history.
Subsequent runs: incremental sync from last sync date.

Environment Variables (optional):
    EMAIL    - Garmin Connect email
    PASSWORD - Garmin Connect password
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from getpass import getpass
from pathlib import Path

import requests
from garth.exc import GarthException, GarthHTTPError

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

logging.getLogger("garminconnect").setLevel(logging.CRITICAL)

BASE_DIR = Path.home() / "garmin_data"
SYNC_STATE_FILE = BASE_DIR / "sync_state.json"
HISTORY_DAYS = 365
API_DELAY = 1.0
MAX_RETRIES = 3
RETRY_BACKOFF = 5

# Tracks failed API calls: { "2026-04-08": ["hydration.json", "hrv.json"], "activities": [...] }
sync_failures: dict[str, list[str]] = {}


def init_api() -> Garmin | None:
    """Initialize Garmin API with token reuse and credential fallback."""
    tokenstore = os.getenv("GARMINTOKENS", "~/.garminconnect")
    tokenstore_path = Path(tokenstore).expanduser()

    # Try stored tokens first
    try:
        garmin = Garmin()
        garmin.login(str(tokenstore_path))
        print("Authenticated with stored tokens.")
        return garmin
    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError,
            GarminConnectConnectionError) as e:
        if not sys.stdin.isatty():
            print(f"Token authentication failed and running non-interactively: {e}")
            print("Re-run manually to refresh tokens: cd ~/dev/my-garmin-data && uv run sync_garmin_data.py")
            return None

    # Prompt for credentials (interactive only)
    while True:
        try:
            email = os.getenv("EMAIL") or input("Login email: ")
            password = os.getenv("PASSWORD") or getpass("Enter password: ")

            garmin = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
            result1, result2 = garmin.login()

            if result1 == "needs_mfa":
                mfa_code = input("Enter MFA code: ")
                try:
                    garmin.resume_login(result2, mfa_code)
                except GarthHTTPError as e:
                    if "429" in str(e):
                        print("Rate limited during MFA. Try again later.")
                        sys.exit(1)
                    elif "401" in str(e) or "403" in str(e):
                        print("Invalid MFA code. Try again.")
                        continue
                    else:
                        sys.exit(1)
                except GarthException:
                    print("MFA failed. Try again.")
                    continue

            garmin.garth.dump(str(tokenstore_path))
            print("Authenticated successfully.")
            return garmin

        except GarminConnectAuthenticationError:
            print("Invalid credentials. Try again.")
            continue
        except (FileNotFoundError, GarthHTTPError, GarminConnectConnectionError,
                requests.exceptions.HTTPError):
            print("Connection error during login.")
            return None
        except KeyboardInterrupt:
            return None


def api_call(api_method, *args, **kwargs):
    """Call an API method with retry on rate limiting. Returns result or None."""
    for attempt in range(MAX_RETRIES):
        try:
            result = api_method(*args, **kwargs)
            return result
        except (GarminConnectTooManyRequestsError, GarthHTTPError) as e:
            if "429" in str(e) or isinstance(e, GarminConnectTooManyRequestsError):
                wait = RETRY_BACKOFF * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            return None
        except Exception as e:
            print(f"  Warning: {e}")
            return None
    print("  Giving up after max retries.")
    return None


def save_json(path: Path, data):
    """Write data as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_sync_state() -> date | None:
    """Load last sync date from state file."""
    if SYNC_STATE_FILE.exists():
        with open(SYNC_STATE_FILE) as f:
            state = json.load(f)
        last = state.get("last_sync_date")
        if last:
            return datetime.strptime(last, "%Y-%m-%d").date()
    return None


def save_sync_state(sync_date: date):
    """Save sync state with current date."""
    save_json(SYNC_STATE_FILE, {"last_sync_date": sync_date.isoformat()})


def sync_daily_data(api: Garmin, start: date, end: date):
    """Sync per-day health metrics."""
    daily_calls = [
        ("summary.json", api.get_user_summary),
        ("heart_rate.json", api.get_heart_rates),
        ("sleep.json", api.get_sleep_data),
        ("stress.json", api.get_all_day_stress),
        ("respiration.json", api.get_respiration_data),
        ("spo2.json", api.get_spo2_data),
        ("hrv.json", api.get_hrv_data),
        ("training_readiness.json", api.get_training_readiness),
        ("hydration.json", api.get_hydration_data),
        ("intensity_minutes.json", api.get_intensity_minutes_data),
        ("floors.json", api.get_floors),
        ("steps_detail.json", api.get_steps_data),
        ("lifestyle_logging.json", api.get_lifestyle_logging_data),
    ]

    # Collect all dates to visit: the requested range + any existing days
    # with missing files (backfills newly added data types automatically)
    daily_dir = BASE_DIR / "daily"
    dates_to_sync = set()
    current = start
    while current <= end:
        dates_to_sync.add(current)
        current += timedelta(days=1)

    expected_files = {fname for fname, _ in daily_calls} | {"body_battery.json"}
    if daily_dir.exists():
        for day_dir in daily_dir.iterdir():
            if not day_dir.is_dir() or not day_dir.name[:4].isdigit():
                continue
            existing_files = {f.name for f in day_dir.iterdir() if f.is_file()}
            if not expected_files.issubset(existing_files):
                dates_to_sync.add(date.fromisoformat(day_dir.name))

    sorted_dates = sorted(dates_to_sync)
    total = len(sorted_dates)
    # Always re-fetch last 2 days (data may be incomplete from earlier syncs)
    refetch_cutoff = end - timedelta(days=1)
    for i, sync_date in enumerate(sorted_dates, 1):
        date_str = sync_date.isoformat()
        day_dir = daily_dir / date_str
        force_refetch = sync_date >= refetch_cutoff
        print(f"Syncing daily data: {date_str}{'  [refresh]' if force_refetch else ''}... {i}/{total}")

        for filename, method in daily_calls:
            filepath = day_dir / filename
            if filepath.exists() and not force_refetch:
                continue
            data = api_call(method, date_str)
            if data is not None:
                save_json(filepath, data)
            else:
                sync_failures.setdefault(date_str, []).append(filename)
            time.sleep(API_DELAY)

        # body_battery takes start+end date params
        bb_path = day_dir / "body_battery.json"
        if not bb_path.exists() or force_refetch:
            data = api_call(api.get_body_battery, date_str, date_str)
            if data is not None:
                save_json(bb_path, data)
            else:
                sync_failures.setdefault(date_str, []).append("body_battery.json")
            time.sleep(API_DELAY)


def sync_activities_full(api: Garmin):
    """Paginate through all activities (initial sync)."""
    print("Syncing all activities (paginated)...")
    activities_dir = BASE_DIR / "activities"
    start = 0
    limit = 100
    total = 0

    while True:
        batch = api_call(api.get_activities, start, limit)
        if not batch:
            break
        for activity in batch:
            aid = activity.get("activityId")
            if not aid:
                continue
            filepath = activities_dir / f"{aid}.json"
            if filepath.exists():
                total += 1
                continue
            # Fetch full detail
            detail = api_call(api.get_activity, str(aid))
            if detail is not None:
                save_json(filepath, detail)
            else:
                # Save summary at minimum
                save_json(filepath, activity)
                sync_failures.setdefault("activities", []).append(f"{aid} (detail only)")
            total += 1
            print(f"  Activity {aid} ({total})")
            time.sleep(API_DELAY)
        if len(batch) < limit:
            break
        start += limit
        time.sleep(API_DELAY)

    print(f"  {total} activities synced.")


def sync_activities_incremental(api: Garmin, start_date: date, end_date: date):
    """Sync activities for a date range (incremental)."""
    print(f"Syncing activities from {start_date} to {end_date}...")
    activities_dir = BASE_DIR / "activities"
    activities = api_call(api.get_activities_by_date, start_date.isoformat(), end_date.isoformat())
    if not activities:
        print("  No new activities.")
        return

    for activity in activities:
        aid = activity.get("activityId")
        if not aid:
            continue
        filepath = activities_dir / f"{aid}.json"
        if filepath.exists():
            continue
        detail = api_call(api.get_activity, str(aid))
        if detail is not None:
            save_json(filepath, detail)
        else:
            save_json(filepath, activity)
            sync_failures.setdefault("activities", []).append(f"{aid} (detail only)")
        print(f"  Activity {aid}")
        time.sleep(API_DELAY)


def sync_body_composition(api: Garmin, start_date: date, end_date: date):
    """Sync body composition and weigh-in data (chunked to avoid API limits)."""
    print("Syncing body composition...")
    bc_dir = BASE_DIR / "body_composition"
    bc_file = bc_dir / "body_comp_full.json"

    # Load existing entries
    all_entries = {}
    if bc_file.exists():
        with open(bc_file) as f:
            for e in json.load(f):
                d = e.get("calendarDate")
                if d:
                    all_entries[d] = e

    # Always refresh last 2 days from API (data may arrive late)
    refetch_start = end_date - timedelta(days=1)

    # Fetch in 60-day chunks — only from refetch_start to end_date
    # (historical data is already in the file)
    chunk_start = refetch_start
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=60), end_date)
        data = api_call(api.get_body_composition, chunk_start.isoformat(), chunk_end.isoformat())
        if data:
            for e in data.get("dateWeightList", []):
                d = e.get("calendarDate")
                if d:
                    all_entries[d] = e
        else:
            sync_failures.setdefault("body_composition", []).append(
                f"{chunk_start} to {chunk_end}")
        time.sleep(API_DELAY)
        chunk_start = chunk_end + timedelta(days=1)

    if all_entries:
        sorted_entries = sorted(all_entries.values(), key=lambda x: x.get("calendarDate", ""))
        save_json(bc_file, sorted_entries)
        print(f"  {len(sorted_entries)} weigh-ins saved")


def sync_weekly(api: Garmin):
    """Sync weekly aggregate trends."""
    print("Syncing weekly trends...")
    weekly_dir = BASE_DIR / "weekly"
    today_str = date.today().isoformat()

    data = api_call(api.get_weekly_steps, today_str, 52)
    if data is not None:
        save_json(weekly_dir / "steps.json", data)
    time.sleep(API_DELAY)

    data = api_call(api.get_weekly_stress, today_str, 52)
    if data is not None:
        save_json(weekly_dir / "stress.json", data)


def sync_profile(api: Garmin):
    """Sync user profile and device info."""
    print("Syncing profile...")
    profile_dir = BASE_DIR / "profile"

    data = api_call(api.get_user_profile)
    if data is not None:
        save_json(profile_dir / "user_profile.json", data)
    time.sleep(API_DELAY)

    data = api_call(api.get_devices)
    if data is not None:
        save_json(profile_dir / "devices.json", data)


def sync_nutrition(api: Garmin, start: date, end: date):
    """Sync daily nutrition/food logs (requires Connect+)."""
    nutrition_dir = BASE_DIR / "nutrition"
    refetch_cutoff = end - timedelta(days=1)

    current = start
    dates_to_sync = []
    while current <= end:
        filepath = nutrition_dir / current.isoformat() / "food_log.json"
        force_refetch = current >= refetch_cutoff
        if not filepath.exists() or force_refetch:
            dates_to_sync.append(current)
        current += timedelta(days=1)

    if not dates_to_sync:
        print("Nutrition: 0 new days to sync")
        return

    print(f"Syncing nutrition ({len(dates_to_sync)} days)...")
    for sync_date in dates_to_sync:
        date_str = sync_date.isoformat()
        day_dir = nutrition_dir / date_str

        # Food log (individual items per meal)
        data = api_call(api.connectapi, f"/nutrition-service/food/logs/{date_str}")
        if data is not None:
            # Skip empty days (no logged foods)
            meals = data.get("mealDetails", [])
            food_count = sum(len(m.get("loggedFoods", [])) for m in meals)
            if food_count > 0:
                save_json(day_dir / "food_log.json", data)
        else:
            sync_failures.setdefault("nutrition", []).append(date_str)
        time.sleep(API_DELAY)


def sync_personal_records(api: Garmin):
    """Sync personal records."""
    print("Syncing personal records...")
    data = api_call(api.get_personal_record)
    if data is not None:
        save_json(BASE_DIR / "personal_records.json", data)


def main():
    api = init_api()
    if not api:
        print("Failed to authenticate.")
        sys.exit(1)

    today = date.today()
    last_sync = load_sync_state()

    if last_sync:
        start_date = last_sync
        print(f"Incremental sync from {start_date} to {today}")
    else:
        start_date = today - timedelta(days=HISTORY_DAYS)
        print(f"Initial sync: {start_date} to {today} ({HISTORY_DAYS} days)")

    sync_start_time = time.time()

    # Daily data
    sync_daily_data(api, start_date, today)
    time.sleep(API_DELAY)

    # Activities
    if last_sync:
        sync_activities_incremental(api, start_date, today)
    else:
        sync_activities_full(api)
    time.sleep(API_DELAY)

    # Body composition
    sync_body_composition(api, start_date, today)
    time.sleep(API_DELAY)

    # Nutrition (requires Connect+, silently skips if unavailable)
    sync_nutrition(api, start_date, today)
    time.sleep(API_DELAY)

    # Weekly trends (always full refresh)
    sync_weekly(api)
    time.sleep(API_DELAY)

    # Profile (always refresh)
    sync_profile(api)
    time.sleep(API_DELAY)

    # Personal records
    sync_personal_records(api)

    # Save state
    save_sync_state(today)

    # Print sync summary
    elapsed = int(time.time() - sync_start_time)
    days_synced = (today - start_date).days + 1
    if sync_failures:
        total_failures = sum(len(v) for v in sync_failures.values())
        print(f"\n⚠ Sync complete ({days_synced} days, {elapsed}s) with {total_failures} failure(s):")
        for key, failures in sorted(sync_failures.items()):
            print(f"  {key}: {', '.join(failures)}")
        print(f"\nData stored in {BASE_DIR}")
    else:
        print(f"\n✓ Sync complete ({days_synced} days, {elapsed}s, no failures). Data stored in {BASE_DIR}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSync interrupted.")
