#!/usr/bin/env python3

import pandas as pd
import glob
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

# ==========================================================
# CONFIGURATION
# ==========================================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

INPUT_DIR = BASE_DIR / "sessions" / "fp" / "refrence-files"   # <-- change if needed
FINAL_OUTPUT_FILE = INPUT_DIR / "filtered.csv"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "port": int(os.environ.get("DB_PORT", 5432)),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASS"),
    "dbname": os.environ.get("DB_NAME")
}

COLUMNS_TO_KEEP = [
    "chid",
    "chname",
    "s3_date",
    "timestamp",
    "device_id",
    "hhid"
]

# Yerevan timezone (UTC +04:00)
TZ_OFFSET = int(os.environ.get("TZ_OFFSET", 4))
YEREVAN_TZ = timezone(timedelta(hours=TZ_OFFSET))

# ==========================================================
# STEP 0: BUILD EXPECTED FILE LIST (D-1 + D LOGIC)
# ==========================================================
today = datetime.now().date()
yesterday = today - timedelta(days=1)

expected_files = []

# D-1 → hours 02 to 23
for hour in range(2, 24):
    fname = f"{yesterday}_{hour:02d}_matched.csv"
    expected_files.append(os.path.join(INPUT_DIR, fname))

# D → hours 00 and 01
for hour in range(0, 2):
    fname = f"{today}_{hour:02d}_matched.csv"
    expected_files.append(os.path.join(INPUT_DIR, fname))

print(f"Expected {len(expected_files)} files")

# ==========================================================
# VALIDATE FILE EXISTENCE (STRICT)
# ==========================================================
missing_files = [f for f in expected_files if not os.path.exists(f)]

if missing_files:
    raise FileNotFoundError(
        f"❌ Missing {len(missing_files)} expected files:\n" +
        "\n".join(missing_files)
    )

print("✅ All expected files found")

# ==========================================================
# STEP 1: READ FILES + CREATE UTC EPOCH
# ==========================================================
dfs = []

for file_path in sorted(expected_files):
    print(f"Processing: {file_path}")
    df = pd.read_csv(file_path)

    if "meter_ts" not in df.columns:
        raise ValueError(f"meter_ts missing in {file_path}")

    df["timestamp"] = (
        pd.to_datetime(df["meter_ts"], format="%Y%m%d_%H%M%S", errors="coerce")
        .dt.tz_localize(YEREVAN_TZ)
        .dt.tz_convert(timezone.utc)
        .astype("int64") // 10**9
    )

    dfs.append(df)

combined_df = pd.concat(dfs, ignore_index=True)
print(f"Rows after merge: {len(combined_df)}")

# ==========================================================
# STEP 3: CREATE device_id
# ==========================================================
if "fp_file" not in combined_df.columns:
    raise ValueError("fp_file column not found — cannot create device_id")

combined_df["device_id"] = (
    combined_df["fp_file"]
    .astype(str)
    .str.split("_", n=1)
    .str[0]
)

print("✅ device_id created")

# ==========================================================
# STEP 4: FETCH meter_id → hhid MAPPING
# ==========================================================
print("Connecting to database...")

conn = psycopg2.connect(**DB_CONFIG)

query = """
SELECT
    h.hhid AS hhid,
    m.meter_id AS meter_id
FROM meters m
JOIN households h
    ON m.assigned_household_id = h.id;
"""

mapping_df = pd.read_sql(query, conn)
conn.close()

print(f"Fetched {len(mapping_df)} meter-household mappings")

# ==========================================================
# STEP 5: MAP device_id → hhid
# ==========================================================
final_df = combined_df.merge(
    mapping_df,
    left_on="device_id",
    right_on="meter_id",
    how="left"
)

final_df.drop(columns=["meter_id"], inplace=True)

missing_hhid = final_df["hhid"].isna().sum()
print(f"Rows without HHID mapping: {missing_hhid}")

# ==========================================================
# STEP 6: FILTER REQUIRED COLUMNS
# ==========================================================
missing_cols = [col for col in COLUMNS_TO_KEEP if col not in final_df.columns]
if missing_cols:
    raise ValueError(f"Missing required columns: {missing_cols}")

final_df = final_df[COLUMNS_TO_KEEP].copy()

# ==========================================================
# STEP 7: ADD TYPE COLUMN + FILTER UNKNOWN
# ==========================================================
final_df["type"] = 42

if "source_type" in combined_df.columns:
    before_count = len(final_df)
    final_df = final_df[combined_df["source_type"] != "UNKNOWN_MATCHED"]
    after_count = len(final_df)

    print(f"Removed {before_count - after_count} UNKNOWN_MATCHED rows")

# ==========================================================
# STEP 8: SAVE OUTPUT
# ==========================================================
final_df.to_csv(FINAL_OUTPUT_FILE, index=False)

print("\n===================================")
print("✅ PIPELINE COMPLETE")
print(f"Final row count: {len(final_df)}")
print(f"Output saved at: {FINAL_OUTPUT_FILE}")
print("===================================")