#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["garminconnect>=0.3.3", "curl_cffi>=0.7.0", "requests>=2.0"]
# ///
"""Audit local Garmin data against the live Garmin Connect API.

Compares lifestyle tags, hydration and food-log sugar for a date range and
rewrites stale local files so they match Garmin. Catches data that was logged
retroactively, after the daily sync had already fetched that day.

Usage:
    uv run audit_garmin_data.py                          # last 30 days
    uv run audit_garmin_data.py --from 2026-02-15 --to 2026-07-12
    uv run audit_garmin_data.py --dry-run                # report only
"""

import argparse
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from garminconnect import Garmin

BASE_DIR = Path.home() / "garmin_data"
DAILY_DIR = BASE_DIR / "daily"
NUTRITION_DIR = BASE_DIR / "nutrition"
API_DELAY = 0.25


def yes_tags(payload) -> set:
    tags = set()
    for item in (payload or {}).get("dailyLogsReport", []):
        if item.get("logStatus") == "YES":
            tags.add(item.get("name"))
        elif item.get("name") == "Alcohol" and item.get("measurementType") == "QUANTITY":
            total = sum(d.get("amount", d.get("value", 0)) or 0 for d in item.get("details", []) or [])
            if total > 0:
                tags.add("Alcohol")
    return tags


def sugar_of(payload) -> float:
    meals = (payload or {}).get("mealDetails", []) or []
    return sum(m.get("mealNutritionContent", {}).get("sugar", 0) or 0 for m in meals)


def fetch(callable_, *args, retries=3):
    for attempt in range(retries):
        try:
            return callable_(*args)
        except Exception as exc:
            if attempt == retries - 1:
                print(f"    API-fout na {retries} pogingen: {exc}", flush=True)
                return None
            time.sleep(5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=(date.today() - timedelta(days=30)).isoformat())
    ap.add_argument("--to", dest="end", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true", help="alleen rapporteren, niets wegschrijven")
    args = ap.parse_args()

    api = Garmin()
    api.login(str(Path(os.getenv("GARMINTOKENS", "~/.garminconnect")).expanduser()))
    print(f"Ingelogd. Audit {args.start} t/m {args.end}" + (" (dry-run)" if args.dry_run else ""), flush=True)

    d = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    dates = []
    while d <= end:
        dates.append(d.isoformat())
        d += timedelta(days=1)

    tag_diffs, water_diffs, sugar_diffs = [], [], []
    for i, ds in enumerate(dates, 1):
        # --- lifestyle tags ---
        remote = fetch(api.get_lifestyle_logging_data, ds)
        if remote is not None:
            lpath = DAILY_DIR / ds / "lifestyle_logging.json"
            local = json.load(open(lpath)) if lpath.exists() else None
            if yes_tags(remote) != yes_tags(local):
                tag_diffs.append((ds, sorted(yes_tags(remote) - yes_tags(local)), sorted(yes_tags(local) - yes_tags(remote))))
                print(f"  TAGS  {ds}: +{tag_diffs[-1][1]} -{tag_diffs[-1][2]}", flush=True)
                if not args.dry_run:
                    lpath.parent.mkdir(parents=True, exist_ok=True)
                    json.dump(remote, open(lpath, "w"), indent=2)
        time.sleep(API_DELAY)

        # --- hydration ---
        rh = fetch(api.get_hydration_data, ds)
        if rh is not None:
            hpath = DAILY_DIR / ds / "hydration.json"
            l_val = json.load(open(hpath)).get("valueInML") if hpath.exists() else None
            if (rh.get("valueInML") or 0) != (l_val or 0):
                water_diffs.append((ds, l_val, rh.get("valueInML")))
                print(f"  WATER {ds}: lokaal={l_val} remote={rh.get('valueInML')}", flush=True)
                if not args.dry_run:
                    hpath.parent.mkdir(parents=True, exist_ok=True)
                    json.dump(rh, open(hpath, "w"), indent=2)
        time.sleep(API_DELAY)

        # --- food log / sugar ---
        rf = fetch(api.connectapi, f"/nutrition-service/food/logs/{ds}")
        if rf is not None:
            npath = NUTRITION_DIR / ds / "food_log.json"
            l_sugar = sugar_of(json.load(open(npath))) if npath.exists() else 0
            if round(sugar_of(rf)) != round(l_sugar):
                sugar_diffs.append((ds, l_sugar, sugar_of(rf)))
                print(f"  SUIKER {ds}: lokaal={round(l_sugar)} remote={round(sugar_of(rf))}", flush=True)
                if not args.dry_run and (rf.get("mealDetails") or []):
                    npath.parent.mkdir(parents=True, exist_ok=True)
                    json.dump(rf, open(npath, "w"), indent=2)
        time.sleep(API_DELAY)

        if i % 25 == 0:
            print(f"  ... {i}/{len(dates)}", flush=True)

    print(f"\nKlaar. tags={len(tag_diffs)}, water={len(water_diffs)}, suiker={len(sugar_diffs)} verschil(len).")
    if args.dry_run and (tag_diffs or water_diffs or sugar_diffs):
        print("Dry-run: niets weggeschreven. Draai zonder --dry-run om lokaal te corrigeren.")


if __name__ == "__main__":
    main()
