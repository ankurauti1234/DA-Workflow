import pandas as pd
import glob
import os
import re
import json
from datetime import datetime, timedelta
from typing import List
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

with open(BASE_DIR / "config" / "channel_mapping.json", "r") as f:
    CHANNEL_CONFIG = json.load(f)

INPUT_DIR = BASE_DIR / "sessions" / "merging"
INPUT_PATTERN = "*.csv"
OUTPUT_DIR = BASE_DIR / "for-panel" / "for-panel-output"

# Channel IDs to remove
CHANNELS_TO_REMOVE = {6, 9, 10, 13, 15, 14}

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# Helper: convert HH:MM:SS(.ms) → reporting-day seconds
# ============================================================
def time_to_seconds(t):
    try:
        if pd.isna(t):
            return None

        h, m, s = str(t).split(":")
        secs = int(h) * 3600 + int(m) * 60 + float(s)

        # Reporting day: 2 AM to 2 AM
        if secs < 7200:
            secs += 86400

        return int(secs)
    except Exception:
        return None

# ============================================================
# Channel Mapping
# ============================================================
CHANNEL_MAP = CHANNEL_CONFIG["name_to_id"]

CHANNEL_MAP_NORM = {k.strip().lower(): v for k, v in CHANNEL_MAP.items()}

# ============================================================
# Utilities
# ============================================================
DATE_REGEX = re.compile(r"\d{4}-\d{2}-\d{2}")

def extract_date_from_filename(filename: str):
    match = DATE_REGEX.search(filename)
    if not match:
        return None
    return datetime.strptime(match.group(), "%Y-%m-%d").date()

def get_files_in_date_range(start_date, end_date) -> List[str]:
    files = glob.glob(os.path.join(INPUT_DIR, INPUT_PATTERN))
    selected = []

    for file_path in files:
        fname = os.path.basename(file_path)
        file_date = extract_date_from_filename(fname)

        if file_date and start_date <= file_date <= end_date:
            selected.append(file_path)

    return sorted(selected)

def prompt_date(prompt_text: str):
    while True:
        val = input(prompt_text).strip()
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            print("❌ Invalid format. Please use YYYY-MM-DD")

# ============================================================
# Core Processing
# ============================================================
def process_file(file_path: str):
    print(f"\n🔄 Processing: {file_path}")

    df = pd.read_csv(file_path)
    original_rows = len(df)

    # --------------------------------------------------------
    # 1. Assign channelid FIRST ✅
    # --------------------------------------------------------
    df["channelid"] = (
        df["channel"]
        .astype(str)
        .str.strip()
        .str.lower()
        .map(CHANNEL_MAP_NORM)
        .fillna(99)
        .astype(int)
    )

    # --------------------------------------------------------
    # 2. Remove unwanted channel IDs ✅
    # --------------------------------------------------------
    removed_count = df["channelid"].isin(CHANNELS_TO_REMOVE).sum()
    df = df[~df["channelid"].isin(CHANNELS_TO_REMOVE)]

    # --------------------------------------------------------
    # 3. Add start_time_secs
    # --------------------------------------------------------
    if "start_time" not in df.columns:
        raise ValueError("Missing 'start_time' column")

    df["start_time_secs"] = df["start_time"].apply(time_to_seconds)

    # --------------------------------------------------------


    # --------------------------------------------------------
    # 4. Remove empty member_id
    # --------------------------------------------------------
    if "member_id" in df.columns:
        df = df.dropna(subset=["member_id"])
        df = df[df["member_id"].astype(str).str.strip() != ""]

    # --------------------------------------------------------
    # 5. Remove channel == "Others"
    # --------------------------------------------------------
    df = df[df["channel"] != "Others"]

    cleaned_rows = len(df)

    # --------------------------------------------------------
    # Output filename
    # --------------------------------------------------------
    if "date" in df.columns and not df["date"].isna().all():
        date_str = str(df["date"].iloc[0])
    else:
        date_str = os.path.splitext(os.path.basename(file_path))[0]

    output_file = os.path.join(OUTPUT_DIR, f"{date_str}_cleaned.csv")

    df.to_csv(output_file, index=False)

    print(
        f"✅ Rows: {original_rows} → {cleaned_rows} | "
        f"❌ Removed: {removed_count} | "
        f"Saved: {output_file}"
    )

# ============================================================
# MAIN
# ============================================================
def main():
    print("\n📅 Auto-processing D-1 files")

    # --------------------------------------------------------
    # Get yesterday's date
    # --------------------------------------------------------
    yesterday = (datetime.now() - timedelta(days=1)).date()

    print(f"📆 Target date: {yesterday}")

    # --------------------------------------------------------
    # Get files only for D-1
    # --------------------------------------------------------
    all_files = glob.glob(os.path.join(INPUT_DIR, INPUT_PATTERN))
    files = []

    for file_path in all_files:
        fname = os.path.basename(file_path)
        file_date = extract_date_from_filename(fname)

        if file_date == yesterday:
            files.append(file_path)

    if not files:
        print(f"⚠️ No files found for {yesterday}")
        return

    print(f"\n📂 {len(files)} file(s) found for processing")

    # --------------------------------------------------------
    # Process files
    # --------------------------------------------------------
    for file_path in sorted(files):
        process_file(file_path)

    print("\n🎉 D-1 processing completed successfully.")
