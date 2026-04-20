import pandas as pd
import glob
import os
from datetime import datetime, timedelta, time
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

INPUT_PATTERN = str(BASE_DIR / "for-panel" / "for-panel-output" / "*_cleaned.csv")
OUTPUT_DIR = BASE_DIR / "cleaned"

TOTAL_LIMIT = 50400       # 14 hours
RULE_B_LIMIT = 5400       # 1.5 hours
MAX_SESSION = 21600       # 6 hours

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# DATABASE CONFIG
# ============================================================
db_config = {
    'host': os.environ.get("DB_HOST"),
    'port': int(os.environ.get("DB_PORT", 5432)),
    'dbname': os.environ.get("DB_NAME"),
    'user': os.environ.get("DB_USER"),
    'password': os.environ.get("DB_PASS")
}

# ============================================================
# FETCH REGION MAPPING
# ============================================================
print("Fetching region mapping from database...")

conn = psycopg2.connect(**db_config)

query = """
SELECT
    h.hhid,
    m.member_code,
    city,
    region
FROM households h
JOIN members m ON h.id = m.household_id
ORDER BY h.hhid, m.member_code;
"""

region_df = pd.read_sql(query, conn)
conn.close()

region_map = (
    region_df[['hhid', 'region']]
    .drop_duplicates()
)

print("Region mapping loaded:", len(region_map))

# ============================================================
# RULE B WINDOW
# ============================================================
RULE_B_START = time(2, 0, 0)
RULE_B_END = time(4, 59, 59)

def is_rule_b_time(t):
    return RULE_B_START <= t <= RULE_B_END

# ============================================================
# LOAD FILES
# ============================================================
files = glob.glob(INPUT_PATTERN)
if not files:
    raise FileNotFoundError("No CSV files found")

# ============================================================
# PROCESS FILES
# ============================================================
for file_path in files:
    df = pd.read_csv(file_path)
    original_rows = len(df)

    # ========================================================
    # ADD REGION
    # ========================================================
    df = df.merge(region_map, on="hhid", how="left")
    df["region"] = df["region"].fillna("Unknown")

    # ========================================================
    # 🔴 FIX DATE PARSING + STANDARD FORMAT
    # ========================================================

    # Clean spaces
   # Clean
    df["date"] = df["date"].astype(str).str.strip().str.replace("/", "-", regex=False)

    # Parse (robust)
    df["start_dt"] = pd.to_datetime(df["date"] + " " + df["start_time"], errors="coerce")
    df["end_dt"] = pd.to_datetime(df["date"] + " " + df["end_time"], errors="coerce")

    # Debug
    print("Invalid start_dt:", df["start_dt"].isna().sum())
    print("Total rows before parsing:", len(df))

    print("Invalid start_dt:", df["start_dt"].isna().sum())
    print("Invalid end_dt:", df["end_dt"].isna().sum())

    # Step 2: Drop bad rows
    df = df.dropna(subset=["start_dt", "end_dt"])

    # The following lines prematurely convert datetime objects to strings,
    # causing TypeError in subsequent timedelta additions. Removed.
    # df["start_dt"] = df["start_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")
    # df["end_dt"] = df["end_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")

    # (Optional) If you want separate date column also fixed
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce").dt.strftime("%Y-%m-%d")

    # End time in 00 or 01 → next day
    df.loc[
        pd.to_datetime(df["end_time"], format="%H:%M:%S").dt.hour.isin([0, 1]),
        "end_dt"
    ] += timedelta(days=1)

    # Recalculate duration
    df["duration_seconds"] = (df["end_dt"] - df["start_dt"]).dt.total_seconds()

    # Remove invalid durations
    df = df[df["duration_seconds"] > 0]

    # ========================================================
    # Create Indi
    # ========================================================
    df["Indi"] = df["hhid"].astype(str) + df["member_id"].astype(str)

    # ========================================================
    # SORT BEFORE MERGING
    # ========================================================
    df = df.sort_values(
        ["Indi", "date", "start_dt"],
        kind="mergesort"
    ).reset_index(drop=True)

    # ========================================================
    # ● MERGE CONTINUOUS SESSIONS
    # ========================================================
    merged_rows = []

    for indi, g in df.groupby("Indi", sort=False):
        g = g.sort_values("start_dt").reset_index(drop=True)

        current = g.iloc[0].copy()

        for i in range(1, len(g)):
            next_row = g.iloc[i]

            # Check merge condition
            if (
                current["channelid"] == next_row["channelid"] and
                current["end_time"] == next_row["start_time"]
            ):
                # Extend current session
                current["end_time"] = next_row["end_time"]
                current["end_dt"] = next_row["end_dt"]

                # Recalculate duration
                duration_sec = (current["end_dt"] - current["start_dt"]).total_seconds()
                current["duration_seconds"] = duration_sec
                current["duration"] = str(timedelta(seconds=duration_sec))

            else:
                merged_rows.append(current)
                current = next_row.copy()

        merged_rows.append(current)

    df = pd.DataFrame(merged_rows)

    # ========================================================
    # Prepare for rules
    # ========================================================
    df["start_time_dt"] = pd.to_datetime(df["start_time"], format="%H:%M:%S")
    df["start_time_t"] = df["start_time_dt"].dt.time

    df = df.sort_values(
        ["hhid", "member_id", "date", "start_time"],
        kind="mergesort"
    ).reset_index(drop=True)

    output_rows = []

     # ========================================================
    # Remove sessions > 6 hours
    # ========================================================
    df = df[df["duration_seconds"] <= MAX_SESSION]

    # ========================================================
    # APPLY RULES
    # ========================================================
    for indi, g in df.groupby("Indi", sort=False):
        total_used = 0
        cutoff = False

        for _, row in g.iterrows():
            if cutoff:
                break

            dur = row["duration_seconds"]
            row_copy = row.copy()

            # Rule A
            if total_used + dur > TOTAL_LIMIT:
                allowed = TOTAL_LIMIT - total_used
                if allowed > 0:
                    row_copy["duration_seconds"] = allowed
                    new_end = row["start_time_dt"] + timedelta(seconds=allowed)
                    row_copy["end_time"] = new_end.strftime("%H:%M:%S")
                    row_copy["duration"] = str(timedelta(seconds=allowed))
                    output_rows.append(row_copy)
                cutoff = True
                break

            # Rule B
            if is_rule_b_time(row["start_time_t"]) and dur > RULE_B_LIMIT:
                continue

            total_used += dur
            output_rows.append(row_copy)

    # ========================================================
    # OUTPUT
    # ========================================================
    final_df = pd.DataFrame(output_rows)

    final_df = final_df.drop(
        columns=["start_time_dt", "start_time_t", "start_dt", "end_dt"],
        errors="ignore"
    )

    if "date" in df.columns and not df["date"].isna().all():
        date_str = str(df["date"].iloc[0])
    else:
        date_str = os.path.splitext(os.path.basename(file_path))[0]

    out_file = os.path.join(OUTPUT_DIR, f"{date_str}_cleaned.csv")
    final_df.to_csv(out_file, index=False)

    cleaned_rows = len(final_df)

    print(
        f"Processed: {os.path.basename(file_path)} | "
        f"Rows: {original_rows} → {cleaned_rows} | "
        f"Output: {os.path.basename(out_file)}"
    )

print("\nBatch cleaning completed successfully.")