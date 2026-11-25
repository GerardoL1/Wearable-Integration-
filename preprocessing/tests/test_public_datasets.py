"""
Checks for public_datasets.py on small made-up rows, so no real dataset is needed.
"""

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import public_datasets as D

REPO = Path(__file__).resolve().parents[2]


def test_feature_columns_match_the_server():
    text = (REPO / "server" / "app" / "readiness" / "features.py").read_text()
    block = text[text.index("FEATURE_COLUMNS = [") : text.index("]", text.index("FEATURE_COLUMNS = ["))]
    assert re.findall(r'"([a-z_]+)"', block) == D.FEATURE_COLUMNS


def test_short_wakeups_are_cut_out_of_sleep():
    t = lambda h, m: datetime(2020, 1, 1, h, m)  # noqa: E731
    pieces = D._cut([(t(1, 0), t(2, 0), "core")], [(t(1, 10), t(1, 12)), (t(1, 30), t(1, 31))])
    assert pieces == [
        (t(1, 0), t(1, 10), "core"),
        (t(1, 12), t(1, 30), "core"),
        (t(1, 31), t(2, 0), "core"),
    ]


def fitbit_night(start="2020-01-01T23:00:00.000"):
    """One Fitbit "stages" log: 30 min light, 60 min deep, 30 min REM, with a 2-minute wake inside the deep."""
    s = pd.Timestamp(start)
    at = lambda minutes: (s + pd.Timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000")  # noqa: E731
    return {
        "type": "stages",
        "levels": {
            "data": [
                {"dateTime": at(0), "level": "light", "seconds": 1800},
                {"dateTime": at(30), "level": "deep", "seconds": 3600},
                {"dateTime": at(90), "level": "rem", "seconds": 1800},
            ],
            "shortData": [{"dateTime": at(50), "level": "wake", "seconds": 120}],
        },
    }


def test_fitbit_wakeups_count_as_awake_and_not_as_sleep():
    stages = D.fitbit_stages([fitbit_night()], "Europe/Oslo")
    minutes = ((stages["end_utc"] - stages["start_utc"]).dt.total_seconds() / 60).groupby(stages["stage"]).sum()
    assert minutes.to_dict() == {"awake": 2.0, "core": 30.0, "deep": 58.0, "rem": 30.0}
    # Oslo is UTC+1 in January.
    assert stages["start_utc"].min() == pd.Timestamp("2020-01-01 22:00", tz="UTC")


def test_layer1_dates_a_fitbit_night_by_its_onset_evening():
    stages = D.fitbit_stages([fitbit_night("2020-01-02T00:30:00.000")], "Europe/Oslo")
    hr_times = pd.date_range("2020-01-02 00:30", periods=120, freq="1min")
    hr = D._samples(hr_times, np.full(120, 52.0), "heart_rate", "Europe/Oslo")
    nights = D.nights_from(stages, hr, pd.DataFrame(), pd.DataFrame())
    assert len(nights) == 1
    # Asleep just after midnight still belongs to the evening before, as in Layer 1.
    assert str(nights["night_date"].iloc[0]) == "2020-01-01"
    assert nights["tst_min"].iloc[0] == 118.0
    assert nights["rhr_night_bpm"].iloc[0] == 52.0


def test_summary_nights_treat_zero_as_missing_and_never_score_tonight_into_its_baseline():
    days = pd.date_range("2021-06-01", periods=10).date
    hrv = D._in_range(pd.Series([40.0] * 8 + [0.0, 80.0]), "hrv_sdnn")
    n = D.summary_nights(days, tst=[420] * 10, tib=[480] * 10, waso=[30] * 10, latency=[10] * 10,
                         awakenings=[4] * 10, hrv=hrv, rhr=[55] * 10)  # fmt: skip
    assert np.isnan(n["hrv_night_ms"].iloc[8])
    assert not n["usable_hrv"].iloc[8]
    assert n["sleep_efficiency_pct"].iloc[0] == 87.5
    # Eight nights of 40 ms before it, so night 10's HRV is far above that baseline.
    assert n["z_hrv"].iloc[9] > 2


def test_xlsx_rows_are_read_without_openpyxl(tmp_path):
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>48</v></c></row>'
        "</sheetData></worksheet>"
    )
    strings = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>p01</t></si></sst>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", strings)
    path = tmp_path / "people.xlsx"
    path.write_bytes(buf.getvalue())
    assert D.read_xlsx_rows(path) == [{"A": "p01", "B": "48"}]
