"""
Muscle tests (Layer 2) from the USB sensor, an Arduino Uno reading the Muscle Sensor V3. The app uploads the
raw samples of one test. They're stored as they came, and process() turns them into the numbers the app shows.

The test is 5 seconds of rest, then a 30-second wall sit. The sensor's output is already a smoothed envelope,
so the numbers are plain averages of it above the resting level. The thresholds here are placeholders, listed
in docs/open_decisions.md under "Muscle recovery (Layer 2)".
"""

import json
import time
from dataclasses import asdict, dataclass

import numpy as np
from fastapi import HTTPException

from app.core import db
from app.schemas.muscle_tests import MuscleTestChange, MuscleTestUpload
from app.services.users import require_user

SCHEMA = """
-- One row per uploaded test. Poor recordings are kept too, so they can be looked at later,
-- but only good ones are listed to the app.
CREATE TABLE IF NOT EXISTS muscle_tests (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    workout_id      TEXT,
    before_test_id  TEXT,             -- the before test the % compares to
    when_taken      TEXT NOT NULL,    -- before, after, next_morning
    muscle          TEXT NOT NULL,
    side            TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,    -- local time, 2026-11-12T18:05
    load            TEXT NOT NULL,
    position        TEXT NOT NULL,
    patch_spot      TEXT NOT NULL,
    device          TEXT NOT NULL,
    gain_note       TEXT,
    hold_seconds    REAL NOT NULL,
    env_mean        REAL NOT NULL,
    env_slope_per_s REAL NOT NULL,
    vs_before_pct   REAL,
    quality_ok      INTEGER NOT NULL,
    quality_note    TEXT,
    stats           TEXT NOT NULL,    -- JSON, see SignalStats
    planned_name    TEXT,             -- before tests: what the person said they'd train
    planned_date    TEXT,
    created_ms      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS muscle_tests_user ON muscle_tests (user_id, recorded_at);
-- The raw stream: little-endian int64 microseconds and uint16 readings.
CREATE TABLE IF NOT EXISTS muscle_test_samples (
    test_id  TEXT PRIMARY KEY,
    time_us  BLOB NOT NULL,
    adc      BLOB NOT NULL
);
"""

ADC_MAX = 1023
CLIP_ADC = 1020
GAP_US = 3000
MAX_SECONDS = 60
MIN_RATE_SAVE = 500  # below this the upload is refused, it can't be the sketch running properly
MIN_RATE_GOOD = 900
MAX_GAP_SHARE = 0.01
MAX_CLIP_SHARE = 0.01
REST_S = 5.0  # the baseline is the median of this first stretch
MIN_HOLD_S = 20.0
MEASURE_S = 20.0  # env_mean is taken over the middle of the hold
SMOOTH_S = 0.5  # finding the hold looks at half-second averages so a flicker doesn't split it
MIN_RISE_ADC = 30  # placeholder: a hold less than this above rest is "barely above baseline"

ERR_LENGTHS = "time_us and adc must have the same number of samples, at least 2."
ERR_ADC = f"Every adc value must be a whole number from 0 to {ADC_MAX}."
ERR_TIME = "time_us must go up with every sample."
ERR_TOO_LONG = f"A test can be at most {MAX_SECONDS} seconds long."
ERR_SLOW = f"The sensor sent fewer than {MIN_RATE_SAVE} samples a second. Check the Arduino sketch and the cable."
ERR_NO_BEFORE = "There's no before test to compare with. Do the before test first."
ERR_ID_TAKEN = "That test id belongs to someone else."


def init_db():
    with db.connect() as conn:
        conn.executescript(SCHEMA)


@dataclass
class Result:
    hold_seconds: float
    env_mean: float
    env_slope_per_s: float
    quality_ok: bool
    quality_note: str | None
    sample_rate_hz: float
    gap_share: float
    clip_share: float
    adc_min: int
    adc_max: int
    baseline_adc: float
    hold_start_s: float | None
    hold_end_s: float | None


def _longest_run(mask: np.ndarray) -> tuple[int, int]:
    """Start and end (exclusive) of the longest stretch of True, (0, 0) when there is none."""
    if not mask.any():
        return 0, 0
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    i = int(np.argmax(ends - starts))
    return int(starts[i]), int(ends[i])


def process(time_us: np.ndarray, adc: np.ndarray) -> Result:
    """The test's numbers from the raw stream. Pure, so it's tested with made-up signals."""
    t = (time_us - time_us[0]) / 1e6
    x = adc.astype(float)
    steps = np.diff(time_us)
    duration = float(t[-1])
    rate = (len(t) - 1) / duration
    gap_share = float(np.mean(steps > GAP_US))
    clip_share = float(np.mean(adc >= CLIP_ADC))
    rest = t < REST_S
    baseline = float(np.median(x[rest] if rest.any() else x[:1]))

    # Half-second averages on a 10 ms grid. A gap leaves empty slots, which take the last value before them.
    slot = (t / 0.01).astype(int)
    sums, counts = np.bincount(slot, weights=x), np.bincount(slot)
    grid = np.full(len(counts), np.nan)
    grid[counts > 0] = sums[counts > 0] / counts[counts > 0]
    filled = np.maximum.accumulate(np.where(np.isnan(grid), -1, np.arange(len(grid))))
    grid = grid[filled]
    width = max(1, round(SMOOTH_S / 0.01))
    smooth = np.convolve(grid, np.ones(width) / width, mode="same")

    # "Well above baseline": over halfway from rest to how high the signal mostly got after the rest.
    after_rest = np.arange(len(smooth)) * 0.01 >= REST_S
    top = float(np.percentile(smooth[after_rest], 90)) if after_rest.any() else baseline
    threshold = baseline + max(MIN_RISE_ADC / 2, 0.5 * (top - baseline))
    start, end = _longest_run((smooth > threshold) & after_rest)
    hold_s = (end - start) * 0.01
    found = hold_s >= MIN_HOLD_S

    h0, h1 = start * 0.01, end * 0.01
    if found:
        mid = (h0 + h1) / 2
        window = (t >= mid - MEASURE_S / 2) & (t < mid + MEASURE_S / 2)
        in_hold = (t >= h0) & (t < h1)
    else:
        # Numbers nobody should trust, but the reply still needs some. quality_ok says so.
        window = in_hold = t >= min(REST_S, duration / 2)
    env_mean = float(np.mean(x[window] - baseline))
    slope = float(np.polyfit(t[in_hold], x[in_hold], 1)[0]) if in_hold.sum() > 1 else 0.0

    problems = []
    if not found:
        problems.append("No 20-second hold was found. Hold the wall sit until the timer ends.")
    if rate < MIN_RATE_GOOD:
        problems.append(f"The sensor sent {rate:.0f} samples a second, under {MIN_RATE_GOOD}. Check the USB cable.")
    if gap_share > MAX_GAP_SHARE:
        problems.append(f"{gap_share:.1%} of the signal was missing. Close anything else using the sensor.")
    if clip_share > MAX_CLIP_SHARE:
        problems.append("The signal hit the top of its range. Turn the gain down on the sensor.")
    if found and env_mean < MIN_RISE_ADC:
        problems.append("The hold was barely above rest.")

    return Result(
        hold_seconds=round(hold_s if found else 0.0, 1),
        env_mean=round(env_mean, 2),
        env_slope_per_s=round(slope, 3),
        quality_ok=not problems,
        quality_note=" ".join(problems) or None,
        sample_rate_hz=round(rate, 1),
        gap_share=round(gap_share, 4),
        clip_share=round(clip_share, 4),
        adc_min=int(np.min(adc)),
        adc_max=int(np.max(adc)),
        baseline_adc=round(baseline, 1),
        hold_start_s=round(h0, 2) if found else None,
        hold_end_s=round(h1, 2) if found else None,
    )


def _checked_stream(body: MuscleTestUpload) -> tuple[np.ndarray, np.ndarray]:
    if len(body.time_us) != len(body.adc) or len(body.adc) < 2:
        raise HTTPException(400, ERR_LENGTHS)
    try:
        time_us = np.array(body.time_us, dtype=np.int64)
    except OverflowError:
        raise HTTPException(400, ERR_TIME) from None
    adc = np.array(body.adc, dtype=np.int64)
    if np.min(adc) < 0 or np.max(adc) > ADC_MAX:
        raise HTTPException(400, ERR_ADC)
    if (np.diff(time_us) <= 0).any():
        raise HTTPException(400, ERR_TIME)
    seconds = (time_us[-1] - time_us[0]) / 1e6
    if seconds > MAX_SECONDS + 1:
        raise HTTPException(400, ERR_TOO_LONG)
    if (len(adc) - 1) / seconds < MIN_RATE_SAVE:
        raise HTTPException(400, ERR_SLOW)
    return time_us, adc


def _reply(row) -> dict:
    planned = {"name": row["planned_name"], "date": row["planned_date"]} if row["planned_name"] else None
    return {
        "id": row["id"],
        "tester_id": row["user_id"],
        "workout_id": row["workout_id"],
        "when": row["when_taken"],
        "muscle": row["muscle"],
        "side": row["side"],
        "recorded_at": row["recorded_at"],
        "hold_seconds": row["hold_seconds"],
        "load": row["load"],
        "position": row["position"],
        "patch_spot": row["patch_spot"],
        "device": row["device"],
        "gain_note": row["gain_note"],
        "env_mean": row["env_mean"],
        "env_slope_per_s": row["env_slope_per_s"],
        "vs_before_pct": row["vs_before_pct"],
        "quality_ok": bool(row["quality_ok"]),
        "quality_note": row["quality_note"],
        "source": "device",
        "planned": planned,
        "stats": json.loads(row["stats"]),
    }


def _row(conn, user_id: str, test_id: str):
    return conn.execute("SELECT * FROM muscle_tests WHERE id = ? AND user_id = ?", (test_id, user_id)).fetchone()


def _before_test(conn, user_id: str, body: MuscleTestUpload):
    """The good before test this one compares to: the one named, or the one linked to the workout."""
    if body.before_test_id:
        return conn.execute(
            "SELECT * FROM muscle_tests WHERE id = ? AND user_id = ? AND when_taken = 'before' AND quality_ok = 1",
            (body.before_test_id, user_id),
        ).fetchone()
    if body.workout_id:
        return conn.execute(
            "SELECT * FROM muscle_tests WHERE user_id = ? AND workout_id = ? AND when_taken = 'before'"
            " AND quality_ok = 1 ORDER BY recorded_at DESC LIMIT 1",
            (user_id, body.workout_id),
        ).fetchone()
    return None


def save_upload(user_id: str, body: MuscleTestUpload) -> dict:
    time_us, adc = _checked_stream(body)
    with db.connect() as conn:
        require_user(conn, user_id)
        taken = conn.execute("SELECT user_id FROM muscle_tests WHERE id = ?", (body.id,)).fetchone()
        if taken is not None:
            # The same Save sent twice gets the first answer back.
            if taken["user_id"] != user_id:
                raise HTTPException(409, ERR_ID_TAKEN)
            return _reply(_row(conn, user_id, body.id))
        before = None
        if body.when != "before":
            before = _before_test(conn, user_id, body)
            if before is None:
                raise HTTPException(400, ERR_NO_BEFORE)
        r = process(time_us, adc)
        pct = None
        if before is not None and r.quality_ok and before["env_mean"] > 0:
            pct = round((r.env_mean / before["env_mean"] - 1) * 100, 1)
        stats = {
            k: v
            for k, v in asdict(r).items()
            if k not in ("hold_seconds", "env_mean", "env_slope_per_s", "quality_ok", "quality_note")
        }
        conn.execute(
            "INSERT INTO muscle_tests (id, user_id, workout_id, before_test_id, when_taken, muscle, side, recorded_at,"
            " load, position, patch_spot, device, gain_note, hold_seconds, env_mean, env_slope_per_s, vs_before_pct,"
            " quality_ok, quality_note, stats, created_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, ?)",
            (
                body.id,
                user_id,
                body.workout_id,
                before["id"] if before else None,
                body.when,
                body.muscle,
                body.side,
                body.recorded_at,
                body.load,
                body.position,
                body.patch_spot,
                body.device,
                body.gain_note,
                r.hold_seconds,
                r.env_mean,
                r.env_slope_per_s,
                pct,
                int(r.quality_ok),
                r.quality_note,
                json.dumps(stats),
                int(time.time() * 1000),
            ),
        )
        conn.execute(
            "INSERT INTO muscle_test_samples (test_id, time_us, adc) VALUES (?, ?, ?)",
            (body.id, time_us.astype("<i8").tobytes(), adc.astype("<u2").tobytes()),
        )
        return _reply(_row(conn, user_id, body.id))


def list_tests(user_id: str, workout_id: str | None) -> list[dict]:
    """Good tests only, newest first. A poor one was never shown as a result, so it isn't listed either."""
    sql = "SELECT * FROM muscle_tests WHERE user_id = ? AND quality_ok = 1"
    args: list = [user_id]
    if workout_id is not None:
        sql += " AND workout_id = ?"
        args.append(workout_id)
    with db.connect() as conn:
        require_user(conn, user_id)
        rows = conn.execute(sql + " ORDER BY recorded_at DESC LIMIT 500", args).fetchall()
    return [_reply(r) for r in rows]


def change(user_id: str, test_id: str, body: MuscleTestChange) -> dict:
    with db.connect() as conn:
        require_user(conn, user_id)
        if _row(conn, user_id, test_id) is None:
            raise HTTPException(404, "No muscle test with that id.")
        if "workout_id" in body.model_fields_set:
            conn.execute("UPDATE muscle_tests SET workout_id = ? WHERE id = ?", (body.workout_id, test_id))
        if "planned" in body.model_fields_set:
            p = body.planned
            conn.execute(
                "UPDATE muscle_tests SET planned_name = ?, planned_date = ? WHERE id = ?",
                (p.name if p else None, p.date if p else None, test_id),
            )
        return _reply(_row(conn, user_id, test_id))
