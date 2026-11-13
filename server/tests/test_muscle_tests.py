"""
Muscle tests from the USB sensor (Layer 2). Every signal here is made up in code, no sensor or recording.

    python -m pytest -q tests/test_muscle_tests.py
"""

import main
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import db
from app.routers import muscle_tests as muscle_router
from app.services import muscle_tests as mt

# main.py doesn't include this router yet (that's the Layer 1 tab's file), so the tests mount it themselves.
app = FastAPI(exception_handlers=main.app.exception_handlers)
app.include_router(muscle_router.router)
mt.init_db()
client = TestClient(app)


def signal(rate=1000, seconds=35.0, rest=5.0, hold_s=30.0, rise=300.0, base=60.0, noise=8.0, slope=0.0, seed=1):
    """A Muscle Sensor V3 style envelope: quiet at rest, then a steady rise for the hold."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds, 1 / rate)
    x = base + rng.normal(0, noise, t.size)
    hold = (t >= rest) & (t < rest + hold_s)
    x[hold] += rise + slope * (t[hold] - rest)
    adc = np.clip(np.round(x), 0, 1023).astype(int)
    return (t * 1e6).astype(np.int64) + 7_000_000, adc


def run(**kw):
    return mt.process(*signal(**kw))


def test_a_clean_hold_gives_its_rise_and_slope():
    r = run(rise=300, slope=2.0)
    assert r.quality_ok and r.quality_note is None
    assert r.baseline_adc == pytest.approx(60, abs=2)
    assert r.hold_seconds == pytest.approx(30, abs=1)
    assert r.env_mean == pytest.approx(300 + 2.0 * 15, rel=0.03)  # the middle 20 s sits around 15 s into the hold
    assert r.env_slope_per_s == pytest.approx(2.0, abs=0.2)
    assert r.sample_rate_hz == pytest.approx(1000, rel=0.01)
    assert r.gap_share == 0 and r.clip_share == 0


def test_staying_relaxed_is_refused():
    r = run(rise=5)
    assert not r.quality_ok
    assert "hold" in r.quality_note


def test_a_short_hold_is_not_a_hold():
    r = run(hold_s=15)
    assert not r.quality_ok and r.quality_note.startswith("No 20-second hold")


def test_a_small_rise_is_barely_above_baseline():
    r = run(rise=20, noise=2)
    assert not r.quality_ok and "barely above rest" in r.quality_note


def test_a_slow_stream_is_poor():
    r = run(rate=800)
    assert not r.quality_ok and "800 samples a second" in r.quality_note


def test_gaps_are_poor():
    time_us, adc = signal()
    keep = np.ones(len(adc), bool)
    for start in range(0, len(adc), 50):  # 4 samples lost every 50, so about 2% of steps are gaps
        keep[start + 20 : start + 24] = False
    r = mt.process(time_us[keep], adc[keep])
    assert r.gap_share == pytest.approx(0.02, abs=0.002)
    assert not r.quality_ok and "missing" in r.quality_note


def test_clipping_is_poor():
    r = run(rise=990)
    assert r.clip_share > mt.MAX_CLIP_SHARE
    assert not r.quality_ok and "gain down" in r.quality_note


# ---------------------------------------------------------------- the endpoints


def person(name):
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (name,))
    return f"/api/v1/users/{name}/muscle-tests"


def body(test_id, when="before", **kw):
    sig = {k: kw.pop(k) for k in list(kw) if k in ("rate", "seconds", "rise", "hold_s", "slope", "seed")}
    time_us, adc = signal(**sig)
    return {
        "id": test_id,
        "when": when,
        "muscle": "quads",
        "side": "left",
        "recorded_at": "2026-11-12T18:05",
        "load": "Body weight",
        "position": "Wall sit, knees at 90°",
        "patch_spot": "Left quads, marked spot",
        "device": "Muscle Sensor V3",
        "gain_note": "Gain knob at half",
        "time_us": time_us.tolist(),
        "adc": adc.tolist(),
        **kw,
    }


def test_before_then_after_gives_the_change():
    url = person("mt_flow")
    before = client.post(url, json=body("mt-b1", rise=300))
    assert before.status_code == 200, before.text
    b = before.json()
    assert b["source"] == "device" and b["quality_ok"] and b["vs_before_pct"] is None and b["workout_id"] is None

    plan = client.patch(f"{url}/mt-b1", json={"planned": {"name": "Leg day", "date": "2026-11-12"}})
    assert plan.json()["planned"] == {"name": "Leg day", "date": "2026-11-12"}
    assert client.patch(f"{url}/mt-b1", json={"workout_id": "w-legs"}).json()["workout_id"] == "w-legs"

    after = client.post(url, json=body("mt-a1", when="after", rise=360, workout_id="w-legs")).json()
    assert after["vs_before_pct"] == pytest.approx(20, abs=2)
    morning = client.post(url, json=body("mt-m1", when="next_morning", rise=315, before_test_id="mt-b1")).json()
    assert morning["vs_before_pct"] == pytest.approx(5, abs=2)

    assert {t["id"] for t in client.get(url, params={"workout_id": "w-legs"}).json()} == {"mt-b1", "mt-a1"}
    assert {t["id"] for t in client.get(url).json()} == {"mt-b1", "mt-a1", "mt-m1"}


def test_a_poor_test_is_stored_but_not_listed():
    url = person("mt_poor")
    r = client.post(url, json=body("mt-weak", rise=5)).json()
    assert r["quality_ok"] is False and r["quality_note"]
    assert client.get(url).json() == []
    with db.connect() as conn:
        raw = conn.execute("SELECT adc FROM muscle_test_samples WHERE test_id = 'mt-weak'").fetchone()
    assert len(raw["adc"]) == 2 * 35000


def test_sending_the_same_test_twice_stores_it_once():
    url = person("mt_twice")
    first = client.post(url, json=body("mt-same")).json()
    assert client.post(url, json=body("mt-same", rise=100)).json() == first
    assert client.post(person("mt_other"), json=body("mt-same")).status_code == 409


def _too_high(b):
    b["adc"][500] = 2000


def _uneven(b):
    b["adc"].pop()


def _backwards(b):
    b["time_us"][100] = b["time_us"][99]


@pytest.mark.parametrize(
    "made, edit, message",
    [
        ({"rate": 400}, None, "fewer than 500"),
        ({"seconds": 62}, None, "at most 60"),
        ({}, _too_high, "0 to 1023"),
        ({}, _uneven, "same number"),
        ({}, _backwards, "go up"),
        ({"when": "after"}, None, "no before test"),
    ],
)
def test_bad_uploads_get_a_plain_400(made, edit, message):
    b = body("mt-bad", **made)
    if edit:
        edit(b)
    r = client.post(person("mt_bad"), json=b)
    assert r.status_code == 400, r.text
    assert message in r.json()["detail"]


@pytest.mark.parametrize("field", ["time_us", "muscle", "device", "recorded_at"])
def test_missing_info_is_refused(field):
    b = body("mt-missing")
    del b[field]
    assert client.post(person("mt_bad"), json=b).status_code == 422
    assert client.post(person("mt_bad"), json={**body("mt-empty"), "muscle": ""}).status_code == 422


def test_unknown_person_and_test():
    assert client.post("/api/v1/users/nobody_here/muscle-tests", json=body("mt-x")).status_code == 404
    url = person("mt_missing")
    assert client.patch(f"{url}/not-a-test", json={"workout_id": None}).status_code == 404
