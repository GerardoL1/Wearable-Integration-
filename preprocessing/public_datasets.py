"""
Public wearable datasets turned into rows like the server's training table, one per person per night.

Watch data with stage timelines (PMData) goes through our own Layer 1 steps: sleep windows, nightly metrics,
quality flags and 28-night baselines. Datasets that only publish nightly summaries (LifeSnaps, the fatigue
study, both Oura sets) are mapped to the same night columns and only the baseline step runs. Either way the
features mean what the server stores for the readiness model, and labels sit in their own columns.

The datasets themselves never go in the repo. build_public_training_table.py reads them from a folder outside it.

    PMData             Fitbit Versa 2, 16 people, Norway, real readiness 0-10      OSF vx4bk
    LifeSnaps          Fitbit Sense, 71 people, Europe, RMSSD + mood check-ins     Zenodo 7229547
    Fatigue study      Fitbit, 207 people, USA, "tired yesterday" 0-4              Zenodo 8018238
    Finnish immigrants Oura, 39 people, Finland, RMSSD, dates shifted for privacy  Dryad qz612jmrn
    UC Irvine students Oura gen 1, 21 people, California, RMSSD + PANAS            Dryad D1WH6T
"""

from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from layer1 import config as C
from layer1.baselines import add_baselines
from layer1.metrics import nightly_metrics
from layer1.quality import flag_quality
from layer1.sleep import find_sleep_windows

# The inputs the server stores for each night (server/app/readiness/features.py). A test checks they match.
FEATURE_COLUMNS = [
    "hrv_night_ms", "hrv_ln", "z_hrv", "rhr_night_bpm", "z_rhr", "tst_min", "z_tst",
    "sleep_efficiency_pct", "z_eff", "fragmentation_per_hr", "z_frag",
    "waso_min", "sleep_latency_min", "naps",
    "usable_sleep", "usable_hrv", "usable_rhr", "flag_short_sleep", "flag_no_hrv", "flag_low_hr_coverage",
    "flag_no_stages", "hrv_count", "hr_slot_count",
    "hrv_ln_base_n", "rhr_night_bpm_base_n", "tst_min_base_n", "sleep_efficiency_pct_base_n",
    "fragmentation_per_hr_base_n",
]  # fmt: skip
EXTRA_NIGHT_COLUMNS = ["core_min", "deep_min", "rem_min", "awakenings", "tib_min", "sleep_onset", "final_wake"]
# Who the person is, for checking the model by group. Exact age where a dataset gives it, otherwise its band.
PERSON_COLUMNS = ["age", "age_band", "gender", "bmi_band"]
LOAD_WINDOWS = {"load_1d": 1, "load_3d": 3, "load_7d": 7, "load_28d": 28}

FITBIT_STAGES = {"light": "core", "deep": "deep", "rem": "rem", "wake": "awake"}
# Fitbit's older "classic" logs. Restless counts as awake in Fitbit's own minutesAwake.
FITBIT_CLASSIC = {"asleep": "asleep_unspecified", "restless": "awake", "awake": "awake"}


# Shared helpers ------------------------------------------------------------------------------------------------


def _timed(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Adds UTC times to rows that only have local wall-clock times, using the person's time zone."""
    out = df.copy()
    for side in ("start", "end"):
        local = out[f"{side}_local"].dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
        out[f"{side}_utc"] = local.dt.tz_convert("UTC")
    return out.dropna(subset=["start_utc", "end_utc"]).sort_values("start_utc").reset_index(drop=True)


def _samples(times, values, metric: str, tz: str) -> pd.DataFrame:
    """Point readings (heart rate) in local time, kept only inside Layer 1's plausible range."""
    df = pd.DataFrame({"start_local": pd.to_datetime(times), "value": pd.to_numeric(values, errors="coerce")})
    df["end_local"] = df["start_local"]
    df = _timed(df, tz)
    lo, hi = C.VALID_RANGES[metric]
    return df[df["value"].between(lo, hi)].assign(metric=metric, kind="quantity").reset_index(drop=True)


def _in_range(values: pd.Series, metric: str) -> np.ndarray:
    """Values outside Layer 1's plausible range count as missing. Fitbit and Oura write 0 for no reading."""
    v = pd.to_numeric(values, errors="coerce")
    return v.where(v.between(*C.VALID_RANGES[metric])).to_numpy(dtype=float)


def nights_from(stages: pd.DataFrame, hr: pd.DataFrame, rhr: pd.DataFrame, hrv: pd.DataFrame) -> pd.DataFrame:
    """Layer 1 steps 3 to 6 on data that's already clean. Every frame has start/end in local and UTC time."""
    # Typed, because Layer 1 reads .dt on these columns even when there are no rows.
    empty = pd.DataFrame(
        {
            "start_utc": pd.Series(dtype="datetime64[ns, UTC]"),
            "end_utc": pd.Series(dtype="datetime64[ns, UTC]"),
            "start_local": pd.Series(dtype="datetime64[ns]"),
            "end_local": pd.Series(dtype="datetime64[ns]"),
            "value": pd.Series(dtype=float),
        }
    )
    cleaned = {
        "heart_rate": hr,
        "resting_heart_rate": rhr if len(rhr) else empty,
        "hrv_sdnn": hrv if len(hrv) else empty,
        "sleep_stages": stages,
        "in_bed": empty.assign(stage=pd.Series(dtype=str)),
    }
    sessions, st = find_sleep_windows(stages)
    metrics = nightly_metrics(sessions, st, cleaned)
    if metrics.empty:
        return metrics
    return add_baselines(flag_quality(metrics))


def summary_nights(night_dates, tst, tib, waso, latency, awakenings, hrv, rhr) -> pd.DataFrame:
    """
    Night columns from datasets that only publish nightly totals (minutes, ms, bpm), then the baseline step.
    Quality flags follow Layer 1's rules where the inputs exist. Missing inputs stay empty, never 0.
    """
    n = pd.DataFrame({"night_date": list(night_dates)})
    tst = np.asarray(tst, dtype=float)
    tib = np.asarray(tib, dtype=float)
    tst = np.where(tst > 0, tst, np.nan)
    awakenings = np.asarray(awakenings, dtype=float)
    n["tst_min"] = tst
    n["tib_min"] = tib
    n["sleep_efficiency_pct"] = np.where(tib > 0, tst / tib * 100, np.nan)
    n["waso_min"] = np.asarray(waso, dtype=float)
    n["sleep_latency_min"] = np.asarray(latency, dtype=float)
    n["awakenings"] = awakenings
    n["fragmentation_per_hr"] = np.where(tst > 0, awakenings / (tst / 60), np.nan)
    n["hrv_night_ms"] = np.asarray(hrv, dtype=float)
    n["hrv_ln"] = np.log(n["hrv_night_ms"])
    n["hrv_count"] = n["hrv_night_ms"].notna().astype(int)
    n["rhr_night_bpm"] = np.asarray(rhr, dtype=float)
    has_sleep = ~np.isnan(tst)
    n["flag_short_sleep"] = has_sleep & (tst < C.MIN_TST_FOR_USABLE_MIN)
    n["usable_sleep"] = has_sleep & ~n["flag_short_sleep"]
    n["flag_no_hrv"] = has_sleep & n["hrv_night_ms"].isna()
    n["usable_hrv"] = n["usable_sleep"] & ~n["flag_no_hrv"]
    n["usable_rhr"] = n["usable_sleep"] & n["rhr_night_bpm"].notna()
    for col in ("naps", "hr_slot_count", "flag_low_hr_coverage", "flag_no_stages", "core_min", "deep_min",
                "rem_min", "sleep_onset", "final_wake"):  # fmt: skip
        n[col] = np.nan
    n = add_baselines(n)
    n["night_date"] = n["night_date"].astype(str)
    return n


def _finish(t: pd.DataFrame, extra: list[str], source: str, device: str, hrv_method, timezone: str) -> pd.DataFrame:
    """Fixed column order, empty load columns where a dataset has no effort ratings, and where it came from."""
    keep = ["person_id", "night_date", *FEATURE_COLUMNS, *EXTRA_NIGHT_COLUMNS, *PERSON_COLUMNS, *extra]
    table = t.reindex(columns=keep).copy()
    for col in [*LOAD_WINDOWS, "rated_workouts_7d"]:
        if col not in t:
            table[col] = np.nan
        else:
            table[col] = t[col]
    table["source"] = source
    table["device"] = device
    table["hrv_method"] = hrv_method
    table["timezone"] = timezone
    return table


def add_load(table: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """sessions: local start day and effort x minutes. Same windows as the server's training table."""
    load = sessions.groupby("day")["load"].sum().to_dict()
    count = sessions.groupby("day").size().to_dict()
    nights = pd.to_datetime(table["night_date"]).dt.date
    for col, days in LOAD_WINDOWS.items():
        table[col] = [round(sum(load.get(n - timedelta(days=i), 0.0) for i in range(days)), 1) for n in nights]
    table["rated_workouts_7d"] = [sum(count.get(n - timedelta(days=i), 0) for i in range(7)) for n in nights]
    return table


def read_xlsx_rows(path: Path) -> list[dict[str, str | None]]:
    """The first sheet of an .xlsx as {column letter: text}, with the standard library only (no openpyxl)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    rows = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{{{ns['m']}}}row"):
        out: dict[str, str | None] = {}
        for c in row.findall("m:c", ns):
            match = re.match(r"[A-Z]+", c.get("r", ""))
            v = c.find("m:v", ns)
            val = v.text if v is not None else None
            if c.get("t") == "s" and val is not None:
                val = shared[int(val)]
            if match:
                out[match.group()] = val
        rows.append(out)
    return rows


# PMData (Fitbit Versa 2, Norway, Nov 2019 to Mar 2020) ---------------------------------------------------------

PMDATA_TZ = "Europe/Oslo"  # the study ran in Norway. Fitbit's times have no offsets, so this is an assumption.


def _cut(pieces: list[tuple], wakes: list[tuple]) -> list[tuple]:
    """Splits sleep pieces around the short wake-ups Fitbit lays over them, so each moment has one stage."""
    out = []
    for start, end, stage in pieces:
        cursor = start
        for ws, we in wakes:
            if we <= cursor or ws >= end:
                continue
            if ws > cursor:
                out.append((cursor, ws, stage))
            cursor = max(cursor, we)
        if cursor < end:
            out.append((cursor, end, stage))
    return out


def fitbit_stages(sleep_logs: list[dict], tz: str) -> pd.DataFrame:
    """
    Fitbit sleep logs as Layer 1 stage pieces. Fitbit keeps short wake-ups (under 3 minutes) in a second list
    on top of the long stages. Layer 1 would let sleep win where they overlap, so they're cut out first.
    """
    rows: list[tuple] = []
    for log in sleep_logs:
        levels = log.get("levels", {})
        mapping = FITBIT_STAGES if log.get("type") == "stages" else FITBIT_CLASSIC

        def spans(items, mapping=mapping):
            for p in items:
                s = pd.Timestamp(p["dateTime"])
                yield s, s + timedelta(seconds=p["seconds"]), mapping.get(p["level"])

        long = [p for p in spans(levels.get("data", [])) if p[2]]
        short = sorted((s, e) for s, e, _ in spans(levels.get("shortData", [])))
        asleep = [p for p in long if p[2] != "awake"]
        rows += _cut(asleep, short) + [p for p in long if p[2] == "awake"] + [(s, e, "awake") for s, e in short]
    df = pd.DataFrame(rows, columns=["start_local", "end_local", "stage"])
    df = df[df["end_local"] > df["start_local"]]
    return _timed(df.drop_duplicates(), tz).assign(kind="sleep", metric="sleep_analysis")


def pmdata_people(root: Path) -> dict[str, dict]:
    """Age, gender and height from participant-overview.xlsx (the headers are on its second row)."""

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    people = {}
    for r in read_xlsx_rows(root / "participant-overview.xlsx")[2:]:
        pid = (r.get("A") or "").strip()
        if not pid.startswith("p"):
            continue
        age = num(r.get("B"))
        people[pid] = {
            "age": int(age) if age else None,
            "height_cm": num(r.get("C")),
            "gender": (r.get("D") or "").strip().upper() or None,  # one cell has a trailing non-breaking space
        }
    return people


def _pmdata_weight(folder: Path) -> float | None:
    path = folder / "googledocs" / "reporting.csv"
    if not path.exists():
        return None
    w = pd.to_numeric(pd.read_csv(path).get("weight"), errors="coerce").dropna()
    w = w[w.between(30, 250)]
    return round(float(w.median()), 1) if len(w) else None


def pmdata_person(folder: Path) -> pd.DataFrame:
    """One PMData participant folder (pmdata/pXX) as training rows."""
    pid = folder.name
    fb = folder / "fitbit"
    stages = fitbit_stages(json.loads((fb / "sleep.json").read_text()), PMDATA_TZ)
    hr_raw = json.loads((fb / "heart_rate.json").read_text())
    hr = _samples([r["dateTime"] for r in hr_raw], [r["value"]["bpm"] for r in hr_raw], "heart_rate", PMDATA_TZ)
    del hr_raw
    # Some people have no daily resting HR file. Ours comes from the heart rate samples, so it's optional.
    rhr_path = fb / "resting_heart_rate.json"
    rhr_raw = [r for r in json.loads(rhr_path.read_text()) if r["value"].get("value")] if rhr_path.exists() else []
    rhr_values = [r["value"]["value"] for r in rhr_raw]
    rhr = _samples([r["dateTime"] for r in rhr_raw], rhr_values, "resting_heart_rate", PMDATA_TZ)
    nights = nights_from(stages, hr, rhr, pd.DataFrame())
    if nights.empty:
        return nights
    table = nights.copy()
    table.insert(0, "person_id", f"pmdata_{pid}")
    table["night_date"] = table["night_date"].astype(str)

    # Training load from the PMSys session reports: perceived effort (RPE, 0 to 10) x minutes.
    srpe = pd.read_csv(folder / "pmsys" / "srpe.csv")
    end = pd.to_datetime(srpe["end_date_time"], utc=True).dt.tz_convert(PMDATA_TZ)
    start = end - pd.to_timedelta(srpe["duration_min"], unit="min")
    load = srpe["perceived_exertion"] * srpe["duration_min"]
    table = add_load(table, pd.DataFrame({"day": start.dt.date, "load": load}))

    # Morning wellness answers. Answered on day D, they describe the night of D-1, as our check-ins do.
    w = pd.read_csv(folder / "pmsys" / "wellness.csv")
    answered = pd.to_datetime(w["effective_time_frame"], utc=True).dt.tz_convert(PMDATA_TZ)
    w["night_date"] = (answered.dt.date - timedelta(days=1)).astype(str)
    w["answered"] = answered
    w = w.sort_values("answered").drop_duplicates("night_date", keep="last")  # the newest answer wins
    labels = pd.DataFrame(
        {
            "night_date": w["night_date"],
            # Our scale is 1 to 10 and PMData's readiness is 0 to 10. Both have 10 as the good end.
            "checkin_ready_to_train": (1 + 0.9 * w["readiness"]).round().astype("Int64"),
            "label_source": "pmdata_readiness",
            "pmdata_readiness_0_10": w["readiness"],
            **{f"pmdata_{c}_1_5": w[c] for c in ("fatigue", "mood", "sleep_quality", "soreness", "stress")},
            "pmdata_sleep_duration_h": w["sleep_duration_h"],
            "checkin_answered_local": w["answered"].dt.strftime("%Y-%m-%dT%H:%M"),
        }
    )
    table = table.merge(labels, on="night_date", how="left")

    weight = _pmdata_weight(folder)
    person = pmdata_people(folder.parent).get(pid, {})
    table["weight_kg"] = weight
    table["age"] = person.get("age")
    table["age_band"] = None if person.get("age") is None else ("<30" if person["age"] < 30 else ">=30")
    table["gender"] = person.get("gender")
    height = person.get("height_cm")
    table["bmi_band"] = f"{weight / (height / 100) ** 2:.0f}" if weight and height else None
    extra = [c for c in labels.columns if c != "night_date"] + ["weight_kg"]
    return _finish(table, extra, "pmdata", "Fitbit Versa 2", None, PMDATA_TZ)


def pmdata(root: Path) -> pd.DataFrame:
    """Every participant under PMData's pmdata/ folder."""
    folders = sorted(root.glob("p[0-9][0-9]"))
    return pd.concat([pmdata_person(f) for f in folders], ignore_index=True)


# LifeSnaps (Fitbit Sense, 71 people, mid 2021 to early 2022) ---------------------------------------------------

LIFESNAPS_MOODS = ["TIRED", "RESTED/RELAXED", "ALERT", "HAPPY", "NEUTRAL", "SAD", "TENSE/ANXIOUS"]
LIFESNAPS_EXTRA = ["resting_hr", "stress_score", "spo2", "full_sleep_breathing_rate", "nightly_temperature",
                   "steps", "lightly_active_minutes", "moderately_active_minutes", "very_active_minutes"]  # fmt: skip
LIFESNAPS_CSV = "rais_anonymized/csv_rais_anonymized/daily_fitbit_sema_df_unprocessed.csv"


def lifesnaps(zip_path: Path) -> pd.DataFrame:
    """
    The daily CSV inside rais_anonymized.zip. Fitbit dates a sleep by the day it ends, so the night is that date
    minus 1 (not checked against raw timestamps). There are no awakening counts, so fragmentation stays empty.
    Overnight HR is Fitbit's non-REM average, the closest match to our lowest 30-minute average.
    """
    df = pd.read_csv(io.BytesIO(zipfile.ZipFile(zip_path).read(LIFESNAPS_CSV)))
    parts = []
    for pid, g in df.groupby("id", sort=False):
        g = g.sort_values("date")
        n = summary_nights(
            (pd.to_datetime(g["date"]) - timedelta(days=1)).dt.date,
            tst=g["minutesAsleep"],
            tib=g["sleep_duration"] / 60000,
            waso=g["minutesAwake"],
            latency=g["minutesToFallAsleep"],
            awakenings=np.full(len(g), np.nan),
            hrv=_in_range(g["rmssd"], "hrv_sdnn"),
            rhr=_in_range(g["nremhr"], "heart_rate"),
        )
        n.insert(0, "person_id", f"lifesnaps_{str(pid)[-8:]}")
        for c in LIFESNAPS_EXTRA:
            n[f"lifesnaps_{c}"] = g[c].to_numpy()
        for m in LIFESNAPS_MOODS:
            n[f"lifesnaps_mood_{m.split('/')[0].lower()}"] = g[m].to_numpy()
        # LifeSnaps only gives age and BMI in bands.
        for col, name in (("age", "age_band"), ("gender", "gender"), ("bmi", "bmi_band")):
            known = g[col].dropna()
            n[name] = known.mode().iloc[0] if len(known) else None
        parts.append(n)
    t = pd.concat(parts, ignore_index=True)
    extra = [c for c in t if c.startswith("lifesnaps_")]
    return _finish(t, extra, "lifesnaps", "Fitbit Sense", "RMSSD", "local (as exported)")


# Sjogren's / lupus / healthy fatigue study (Zenodo 8018238, Fitbit, USA, 2020) --------------------------------

# "Did you feel tired yesterday?" and friends, as 0 (none) up to the worst answer.
FATIGUE_SCALES = {
    "tired_yesterday": ["not_at_all", "a_little_bit", "somewhat", "quite_a_bit", "very_much"],
    "pain_yesterday": ["not_at_all", "slight_pain", "moderate_pain", "severe_pain", "extreme_pain"],
    "depressed_yesterday": ["not_at_all", "slightly", "moderately", "severely", "extremely"],
    "usual_activities_problems": ["not_at_all", "slight_problems", "moderate_problems", "severe_problems",
                                  "extreme_problems"],
    "day_rating": ["bad", "average", "good"],
}  # fmt: skip


def fatigue_study(folder: Path) -> pd.DataFrame:
    """
    Daily Fitbit summaries. The night comes from the main sleep's own local start time, the way Layer 1 dates
    a night (onset minus 12 hours). Heart rate is the mean while asleep, so it reads a few bpm above ours.
    The daily questions are about yesterday (day D-1), which came after the night of D-2.
    """
    a = pd.read_csv(folder / "day_activity_features.csv")
    a = a[a["sleep__main_start_time"].notna()].copy()
    onset = pd.to_datetime(a["sleep__main_start_time"].str.slice(0, 19))  # local wall clock, offset dropped
    a["night_date"] = (onset - timedelta(hours=C.NIGHT_SHIFT_HOURS)).dt.date
    a["onset"] = onset
    a = a.sort_values(["user_id", "night_date"]).drop_duplicates(["user_id", "night_date"], keep="last")

    people = pd.read_csv(folder / "screener_survey.csv").drop_duplicates("user_id").set_index("user_id")
    surveys = pd.read_csv(folder / "daily_surveys_one_click_responses.csv")
    answered = pd.to_datetime(surveys["survey_start_datetime"].str.slice(0, 19))
    surveys["night_date"] = (answered - timedelta(days=2)).dt.date.astype(str)
    surveys = surveys.sort_values("survey_start_datetime").drop_duplicates(["user_id", "night_date"], keep="last")
    label_cols = []
    for col, order in FATIGUE_SCALES.items():
        surveys[f"fatigue_{col}"] = surveys[col].map({v: i for i, v in enumerate(order)})
        label_cols.append(f"fatigue_{col}")

    parts = []
    for pid, g in a.groupby("user_id", sort=False):
        n = summary_nights(
            g["night_date"],
            tst=g["sleep__main_asleep_minutes"],
            tib=g["sleep__main_in_bed_minutes"],
            waso=g["sleep__loop_main_awake_minutes"],
            latency=g["sleep__loop_main_until_sleep_minutes"],
            awakenings=g["sleep__loop_main_awake_region_count"],
            hrv=np.full(len(g), np.nan),
            rhr=_in_range(g["heart_rate__asleep__mean"], "heart_rate"),
        )
        n["naps"] = g["sleep__nap_count"].to_numpy(dtype=float)
        n["sleep_onset"] = g["onset"].to_numpy()
        n.insert(0, "person_id", f"fatigue_{pid}")
        n["fitbit_resting_hr"] = g["heart_rate__resting_heart_rate"].to_numpy()
        p = people.loc[pid] if pid in people.index else None
        age = float(p["age"]) if p is not None and pd.notna(p["age"]) else np.nan
        n["age"] = age
        n["age_band"] = None if np.isnan(age) else ("<30" if age < 30 else ">=30")
        n["gender"] = str(p["sex"]).upper() if p is not None else None
        n["ethnicity"] = p["ethnicity"] if p is not None else None
        n["diagnosis"] = p["diagnosis"] if p is not None else None
        labels = surveys.loc[surveys["user_id"] == pid, ["night_date", *label_cols]]
        parts.append(n.merge(labels, on="night_date", how="left"))
    t = pd.concat(parts, ignore_index=True)
    t["label_source"] = np.where(t["fatigue_tired_yesterday"].notna(), "fatigue_tired_yesterday", None)
    extra = ["ethnicity", "diagnosis", "fitbit_resting_hr", *label_cols, "label_source"]
    return _finish(t, extra, "fatigue_study", "Fitbit (model not stated)", None, "local (offsets in file)")


# Finnish immigrants loneliness study (Dryad qz612jmrn, Oura ring, Finland 2022-23) -----------------------------

FINNISH_EMA = ["lonely", "connect", "isolate", "positive", "negative"]
OURA_COLUMNS = ["OURA_sleep_total", "OURA_sleep_duration", "OURA_sleep_awake", "OURA_sleep_onset_latency",
                "OURA_sleep_wake_up_count", "OURA_sleep_deep", "OURA_sleep_rem", "OURA_sleep_light",
                "OURA_sleep_rmssd", "OURA_sleep_hr_lowest", "OURA_readiness_score"]  # fmt: skip


def finnish_immigrants(outer_zip: Path) -> pd.DataFrame:
    """
    Dryad's download zip, which holds Loneliness_Dataset_Nov10.zip. Every timestamp was shifted by a random
    offset per the README, so dates aren't real. Order and spacing are, which is all the baselines need.
    Weekday and season mean nothing for these people. Only group-level demographics are published.
    """
    inner = zipfile.ZipFile(zipfile.ZipFile(outer_zip).open("Loneliness_Dataset_Nov10.zip"))
    names = set(inner.namelist())
    parts = []
    for name in sorted(n for n in names if "/Oura/oura_data_" in n):
        pid = name.split("/")[0]
        o = pd.read_csv(io.BytesIO(inner.read(name)), low_memory=False)
        if "OURA_sleep_total" not in o:
            continue
        # Not every participant's file has every column, so a missing one reads as empty.
        o = o.reindex(columns=sorted(set(o.columns) | set(OURA_COLUMNS)))
        s = o[o["OURA_sleep_total"].notna()].copy()
        if s.empty:
            continue
        local = pd.to_datetime(s["timestamp"], unit="ms", utc=True).dt.tz_convert("Europe/Helsinki")
        s["night_date"] = local.dt.date - timedelta(days=1)
        # The day's main sleep is its longest one, as Layer 1 picks it.
        s = s.sort_values("OURA_sleep_total").drop_duplicates("night_date", keep="last").sort_values("night_date")
        n = summary_nights(
            s["night_date"],
            tst=s["OURA_sleep_total"] / 60,
            tib=s["OURA_sleep_duration"] / 60,
            waso=s["OURA_sleep_awake"] / 60,
            latency=s["OURA_sleep_onset_latency"] / 60,
            awakenings=s["OURA_sleep_wake_up_count"],
            hrv=_in_range(s["OURA_sleep_rmssd"], "hrv_sdnn"),
            rhr=_in_range(s["OURA_sleep_hr_lowest"], "heart_rate"),  # Oura's lowest 5-minute HR
        )
        for stage, col in (("deep", "OURA_sleep_deep"), ("rem", "OURA_sleep_rem"), ("core", "OURA_sleep_light")):
            n[f"{stage}_min"] = (s[col] / 60).to_numpy(dtype=float)
        n.insert(0, "person_id", f"finnish_{pid.split('_')[-1]}")
        # Oura's own readiness score, for comparison only. It's the vendor's formula, never a label.
        n["oura_readiness_score"] = s["OURA_readiness_score"].to_numpy()
        ema_name = f"{pid}/Surveys/ema_data_{pid}.csv"
        if ema_name in names:
            ema = pd.read_csv(io.BytesIO(inner.read(ema_name)))
            # Up to five answers a day (0 to 10). The day's mean describes the day after the night of D-1.
            ema["night_date"] = (pd.to_datetime(ema["date"]) - timedelta(days=1)).dt.date.astype(str)
            daily = ema.groupby("night_date")[FINNISH_EMA].mean().add_prefix("finnish_ema_").reset_index()
            n = n.merge(daily, on="night_date", how="left")
        parts.append(n)
    t = pd.concat(parts, ignore_index=True)
    extra = ["oura_readiness_score", *[f"finnish_ema_{c}" for c in FINNISH_EMA]]
    return _finish(t, extra, "finnish_immigrants", "Oura ring", "RMSSD", "Europe/Helsinki, dates randomly shifted")


# UC Irvine students (Dryad D1WH6T, Oura ring, Southern California 2020-21) -------------------------------------

UCI_TZ = "America/Los_Angeles"
PANAS_POSITIVE = ["Active", "Alert", "Attentive", "Determined", "Enthusiastic", "Excited", "Inspired", "Interested",
                  "Proud", "Strong"]  # fmt: skip
PANAS_NEGATIVE = ["Afraid", "Ashamed", "Distressed", "Guilty", "Hostile", "Irritable", "Jittery", "Nervous", "Scared",
                  "Upset"]  # fmt: skip


def uci_students(outer_zip: Path) -> pd.DataFrame:
    """
    Dryad's download zip, which holds ifh_affect.zip. Oura's nightly "date" is already the day before the
    wake-up date, which is our night. Per-person age and gender are only shared on request, and the study
    says everyone was 18 to 22. The Samsung watch files are raw sensor streams and aren't used.
    """
    inner = zipfile.ZipFile(zipfile.ZipFile(outer_zip).open("ifh_affect.zip"))
    names = set(inner.namelist())
    parts = []
    for pid in sorted({n.split("/")[0] for n in names if n.endswith("/oura/sleep.csv")}):
        s = pd.read_csv(io.BytesIO(inner.read(f"{pid}/oura/sleep.csv")), low_memory=False)
        s = s[pd.to_numeric(s["total"], errors="coerce") > 0].copy()
        if s.empty:
            continue
        s["night_date"] = pd.to_datetime(s["date"]).dt.date
        s = s.sort_values("total").drop_duplicates("night_date", keep="last").sort_values("night_date")

        def num(col, s=s):
            return pd.to_numeric(s[col], errors="coerce")

        n = summary_nights(
            s["night_date"],
            tst=num("total") / 60,
            tib=num("duration") / 60,
            waso=num("awake") / 60,
            latency=num("onset_latency") / 60,
            awakenings=np.full(len(s), np.nan),  # no wake-up count in this export
            hrv=_in_range(s["rmssd"], "hrv_sdnn"),
            rhr=_in_range(s["hr_lowest"], "heart_rate"),
        )
        for stage, col in (("deep", "deep"), ("rem", "rem"), ("core", "light")):
            n[f"{stage}_min"] = (num(col) / 60).to_numpy(dtype=float)
        for side, col in (("sleep_onset", "bedtime_start_timestamp"), ("final_wake", "bedtime_end_timestamp")):
            local = pd.to_datetime(num(col), unit="ms", utc=True).dt.tz_convert(UCI_TZ)
            n[side] = local.dt.tz_localize(None).to_numpy()
        n.insert(0, "person_id", f"uci_{pid.split('_')[-1]}")

        r_name = f"{pid}/oura/readiness.csv"
        if r_name in names:
            r = pd.read_csv(io.BytesIO(inner.read(r_name))).drop_duplicates("date", keep="last")
            r = r.rename(columns={"date": "night_date", "score": "oura_readiness_score"})
            n = n.merge(r[["night_date", "oura_readiness_score"]], on="night_date", how="left")
        e_name = f"{pid}/ema/daily.csv"
        if e_name in names:
            e = pd.read_csv(io.BytesIO(inner.read(e_name)), low_memory=False)
            for c in PANAS_POSITIVE + PANAS_NEGATIVE:
                e[c] = pd.to_numeric(e.get(c), errors="coerce")
            # "How you felt today", answered on day D. That day follows the night of D-1.
            day = pd.to_datetime(e["submission_timestamp"], unit="ms", utc=True).dt.tz_convert(UCI_TZ).dt.date
            e["night_date"] = (day - timedelta(days=1)).astype(str)
            e["uci_panas_positive"] = e[PANAS_POSITIVE].mean(axis=1)
            e["uci_panas_negative"] = e[PANAS_NEGATIVE].mean(axis=1)
            for c in ("Active", "Alert", "Strong"):
                e[f"uci_{c.lower()}"] = e[c]
            cols = ["uci_panas_positive", "uci_panas_negative", "uci_active", "uci_alert", "uci_strong"]
            n = n.merge(e.groupby("night_date")[cols].mean().reset_index(), on="night_date", how="left")
        parts.append(n)
    t = pd.concat(parts, ignore_index=True)
    t["age_band"] = "<30"
    extra = ["oura_readiness_score", "uci_panas_positive", "uci_panas_negative", "uci_active", "uci_alert",
             "uci_strong"]  # fmt: skip
    return _finish(t, extra, "uci_students", "Oura ring (gen 1)", "RMSSD", UCI_TZ)
