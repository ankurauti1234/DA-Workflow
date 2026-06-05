import pandas as pd
from pathlib import Path

# ===============================
# CONFIG (DYNAMIC PATHS)
# ===============================
BASE_DIR = Path(__file__).resolve().parent.parent.parent

INPUT_CSV = BASE_DIR / "sessions" / "fp" / "output" / "merged_timeline.csv"
OUTPUT_CSV = BASE_DIR / "sessions" / "fp" / "output" / "sessions_output.csv"

SESSION_GAP_SEC = 300          # 5 minutes
SINGLE_EVENT_PADDING = 10      # fallback duration
SINGLE_EVENT_NEXT_LIMIT = 20   # use next event if within 20 sec

# Broadcast day (02:00 → next day 02:00)
BROADCAST_START = 2 * 3600
BROADCAST_END = 26 * 3600


# ===============================
# HELPER FUNCTIONS
# ===============================
def hhmmss_to_broadcast_seconds(t):
    h, m, s = map(int, t.split(":"))
    sec = h * 3600 + m * 60 + s

    # Shift early morning to next day
    if sec < BROADCAST_START:
        sec += 24 * 3600

    return sec


def seconds_to_hhmmss(sec):
    sec = int(sec) % (24 * 3600)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ===============================
# READ DATA
# ===============================
df = pd.read_csv(INPUT_CSV)

# Keep only channel recognition events
df = df[df["type"] == 42].copy()

# Convert time
df["start_secs"] = df["start_time"].apply(hhmmss_to_broadcast_seconds)

# Sort (important fix)
df = df.sort_values(["hhid", "timestamp", "start_secs"]).reset_index(drop=True)


# ===============================
# SESSION IDENTIFICATION
# ===============================
df["prev_timestamp"] = df.groupby("hhid")["timestamp"].shift(1)
df["prev_chname"] = df.groupby("hhid")["chname"].shift(1)

df["time_diff"] = df["timestamp"] - df["prev_timestamp"]

df["new_session"] = (
    (df["chname"] != df["prev_chname"]) |
    (df["time_diff"] > SESSION_GAP_SEC) |
    (df["prev_timestamp"].isna())
)

df["session_id"] = df.groupby("hhid")["new_session"].cumsum()


# ===============================
# BUILD SESSIONS
# ===============================
sessions = []

for (hhid, session_id), grp in df.groupby(["hhid", "session_id"]):

    grp = grp.sort_values("timestamp")

    first = grp.iloc[0]
    last = grp.iloc[-1]

    start_secs = first["start_secs"]
    start_time = first["start_time"]
    s3_date = first["s3_date"]

    # -----------------------------------
    # SINGLE EVENT SESSION
    # -----------------------------------
    if len(grp) == 1:

        next_rows = df[
            (df["hhid"] == hhid) &
            (df.index > first.name)
        ]

        if not next_rows.empty:
            next_event = next_rows.iloc[0]
            gap = next_event["timestamp"] - first["timestamp"]

            if gap <= SINGLE_EVENT_NEXT_LIMIT:
                end_secs = next_event["start_secs"]
            else:
                end_secs = start_secs + SINGLE_EVENT_PADDING
        else:
            end_secs = start_secs + SINGLE_EVENT_PADDING

    # -----------------------------------
    # MULTI EVENT SESSION
    # -----------------------------------
    else:

        next_rows = df[
            (df["hhid"] == hhid) &
            (df.index > last.name)
        ]

        if not next_rows.empty:
            next_event = next_rows.iloc[0]
            gap = next_event["timestamp"] - last["timestamp"]

            if gap <= SESSION_GAP_SEC:
                end_secs = next_event["start_secs"]
            else:
                end_secs = last["start_secs"]
        else:
            end_secs = last["start_secs"]

    # -----------------------------------
    # BROADCAST BOUNDARY FIX (CRITICAL)
    # -----------------------------------
    if end_secs > BROADCAST_END:
        end_secs = BROADCAST_END

    # Safety check
    if end_secs < start_secs:
        end_secs = start_secs

    duration = end_secs - start_secs
    end_time = seconds_to_hhmmss(end_secs)

    sessions.append({
        "hhid": hhid,
        "s3_date": s3_date,
        "chid": first["chid"],
        "chname": first["chname"],
        "start_time": start_time,
        "end_time": end_time,
        "duration": duration,   # kept same naming as Script 1
        "member_id": "",
        "start_secs": start_secs,
        "type": 42
    })


# ===============================
# OUTPUT
# ===============================
sessions_df = pd.DataFrame(sessions)

sessions_df = sessions_df.sort_values(
    ["hhid", "s3_date", "start_time"]
).reset_index(drop=True)

sessions_df.to_csv(OUTPUT_CSV, index=False)

print(f"Sessionization complete. Output written to {OUTPUT_CSV}")
