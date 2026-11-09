"""Behavioral checks for the notebook using in-memory synthetic fixtures only.

These observations are test fixtures, not readiness labels for the original CSVs.
Run with: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pickle
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / ".notebook_deps"
if LOCAL_DEPS.is_dir():
    sys.path.insert(0, str(LOCAL_DEPS))

import numpy as np
import pandas as pd


def load_notebook_definitions() -> dict:
    notebook = json.loads((ROOT / "__notebook_source__.ipynb").read_text(encoding="utf-8"))
    module = types.ModuleType("ridge_notebook_under_test")
    module.__file__ = str(ROOT / "__notebook_source__.ipynb")
    sys.modules[module.__name__] = module
    namespace = module.__dict__
    definition_cells = [
        cell for cell in notebook["cells"]
        if cell["cell_type"] == "code" and cell.get("metadata", {}).get("role") == "definitions"
    ]
    if not definition_cells:
        raise AssertionError("Notebook has no executable definition cells")
    for cell in definition_cells:
        source = "".join(cell["source"])
        exec(compile(source, str(ROOT / "__notebook_source__.ipynb"), "exec"), namespace)
    return namespace


def synthetic_nights(people: int = 4, nights: int = 40) -> pd.DataFrame:
    """Deterministic fixtures with no connection to the original wearable files."""
    rows = []
    for person in range(people):
        for day, date in enumerate(pd.date_range("2025-01-01", periods=nights, freq="D")):
            rows.append({
                "tester_id": f"P{person + 1:02d}",
                "night_date": date.strftime("%Y-%m-%d"),
                "device_name": "Apple Watch SE 2020",
                "hrv_method": "SDNN",
                "hrv": 43.0 + 2 * person + day % 7 + day * 0.1,
                "rhr": 58.0 + person + day % 4,
                "total_sleep_min": 390.0 + person * 4 + day % 9 * 8,
                "ready_rating": int(3 + (person + day) % 7),
            })
    return pd.DataFrame(rows)


class NotebookFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_notebook_definitions()

    def setUp(self):
        self.config = copy.deepcopy(self.ns["DEFAULT_CONFIG"])
        self.config.update(alpha_grid=[0.1, 1.0, 10.0], outer_splits=3, inner_splits=3)

    def features(self, frame):
        cleaned, report = self.ns["validate_nightly"](frame, self.config)
        return self.ns["build_features"](cleaned, self.config), report

    def test_first_seven_nights_are_not_baseline_ready(self):
        table, _ = self.features(synthetic_nights(people=1))
        table = table.sort_values("night_date").reset_index(drop=True)
        self.assertTrue((table.loc[:6, "baseline_ready"] == 0).all())
        self.assertEqual(int(table.loc[7, "baseline_ready"]), 1)

    def test_current_hrv_does_not_enter_its_own_baseline(self):
        data = synthetic_nights(people=1)
        table, _ = self.features(data)
        expected = (data.loc[7, "hrv"] - data.loc[:6, "hrv"].mean()) / data.loc[:6, "hrv"].std(ddof=0)
        self.assertAlmostEqual(float(table.loc[7, "z_hrv"]), expected, places=10)
        altered = data.copy()
        altered.loc[7, "hrv"] = 180.0
        new, _ = self.features(altered)
        self.assertAlmostEqual(float(new.loc[7, "hrv_trend"]), float(table.loc[7, "hrv_trend"]), places=10)
        self.assertAlmostEqual(float(new.loc[7, "rhr_delta"]), float(table.loc[7, "rhr_delta"]), places=10)

    def test_future_sensor_changes_do_not_change_earlier_features(self):
        data = synthetic_nights(people=2)
        original, _ = self.features(data)
        altered = data.copy()
        future = altered["night_date"] > "2025-01-25"
        altered.loc[future, "hrv"] = 210.0
        altered.loc[future, "rhr"] = 110.0
        altered.loc[future, "total_sleep_min"] = 800.0
        new, _ = self.features(altered)
        columns = ["tester_id", "night_date", *self.config["derived_features"], "baseline_ready"]
        before = original.loc[pd.to_datetime(original["night_date"]) <= pd.Timestamp("2025-01-25"), columns].reset_index(drop=True)
        after = new.loc[pd.to_datetime(new["night_date"]) <= pd.Timestamp("2025-01-25"), columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(before, after)

    def test_label_changes_do_not_change_sensor_features(self):
        data = synthetic_nights(people=2)
        original, _ = self.features(data)
        altered = data.copy()
        altered["ready_rating"] = 11 - altered["ready_rating"]
        new, _ = self.features(altered)
        pd.testing.assert_frame_equal(original.drop(columns="ready_rating"), new.drop(columns="ready_rating"))

    def test_calendar_gap_does_not_reuse_stale_baselines(self):
        data = synthetic_nights(people=1, nights=35)
        last = data.iloc[-1].copy()
        last["night_date"] = (pd.Timestamp(last["night_date"]) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        table, _ = self.features(pd.concat([data, pd.DataFrame([last])], ignore_index=True))
        self.assertEqual(int(table.iloc[-1]["baseline_ready"]), 0)
        self.assertTrue(pd.isna(table.iloc[-1]["z_hrv"]))

    def test_duplicate_person_night_is_rejected(self):
        data = synthetic_nights(people=1)
        data = pd.concat([data, data.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            self.features(data)

    def test_training_requires_actual_target(self):
        data = synthetic_nights().drop(columns="ready_rating")
        with self.assertRaises(ValueError):
            self.ns["validate_nightly"](data, self.config, require_target=True)

    def test_fractional_or_out_of_range_target_is_rejected(self):
        for value in (0, 11, 4.5):
            with self.subTest(value=value):
                data = synthetic_nights(people=1)
                data["ready_rating"] = data["ready_rating"].astype(float)
                data.loc[4, "ready_rating"] = value
                with self.assertRaises(ValueError):
                    self.ns["validate_nightly"](data, self.config, require_target=True)

    def test_missing_hrv_is_not_fabricated(self):
        data = synthetic_nights()
        data["hrv"] = np.nan
        with self.assertRaises(ValueError):
            cleaned, _ = self.ns["validate_nightly"](data, self.config, require_target=True)
            table = self.ns["build_features"](cleaned, self.config)
            self.ns["train_ridge"](table, self.config)

    def test_mixed_devices_require_explicit_approval(self):
        data = synthetic_nights(people=1)
        data.loc[20:, "device_name"] = "Apple Watch Ultra"
        with self.assertRaises(ValueError):
            self.features(data)

    def test_rmssd_cannot_silently_replace_sdnn(self):
        data = synthetic_nights(people=1)
        data["hrv_method"] = "RMSSD"
        with self.assertRaises(ValueError):
            self.features(data)

    def test_invalid_rhr_is_flagged_and_kept_missing(self):
        data = synthetic_nights(people=1)
        data.loc[12, "rhr"] = 150.0
        table, report = self.features(data)
        self.assertTrue(pd.isna(table.loc[12, "rhr"]))
        self.assertEqual(int(table.loc[12, "has_rhr"]), 0)
        self.assertEqual(len(table), len(data))
        self.assertIn("rhr", str(report).lower())


class NotebookTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_notebook_definitions()
        cls.config = copy.deepcopy(cls.ns["DEFAULT_CONFIG"])
        cls.config.update(alpha_grid=[0.1, 1.0], outer_splits=3, inner_splits=3)
        cls.data = synthetic_nights()
        cleaned, _ = cls.ns["validate_nightly"](cls.data, cls.config, require_target=True)
        cls.table = cls.ns["build_features"](cleaned, cls.config)
        cls.bundle = cls.ns["train_ridge"](cls.table, cls.config)

    def test_each_person_is_in_exactly_one_outer_test_fold(self):
        oof = self.bundle["oof_predictions"]
        self.assertTrue({"fold", "tester_id"}.issubset(oof.columns))
        self.assertTrue((oof.groupby("tester_id")["fold"].nunique() == 1).all())
        self.assertEqual(set(oof["tester_id"]), set(self.data["tester_id"]))

    def test_target_and_identity_are_not_model_inputs(self):
        inputs = set(self.bundle["feature_columns"])
        self.assertFalse(inputs & {"ready_rating", "tester_id", "night_date", "device_name", "hrv_method"})
        self.assertTrue({"hrv", "rhr", "total_sleep_min"}.issubset(inputs))

    def test_prediction_respects_warmup_and_scale(self):
        predictions = self.ns["predict_readiness"](self.bundle, self.data.drop(columns="ready_rating"))
        valid = predictions["predicted_ready_rating"].notna()
        self.assertTrue(valid.any())
        self.assertTrue(predictions.loc[valid, "predicted_ready_rating"].between(1, 10).all())
        first_seven = predictions.sort_values(["tester_id", "night_date"]).groupby("tester_id").head(7)
        self.assertTrue(first_seven["predicted_ready_rating"].isna().all())
        self.assertTrue({"raw_prediction", "prediction_status"}.issubset(predictions.columns))

    def test_serialized_bundle_reproduces_predictions(self):
        restored = pickle.loads(pickle.dumps(self.bundle))
        inputs = self.data.drop(columns="ready_rating")
        expected = self.ns["predict_readiness"](self.bundle, inputs)
        actual = self.ns["predict_readiness"](restored, inputs)
        pd.testing.assert_frame_equal(expected, actual)

    def test_31_prior_nights_reproduce_full_history_latest_prediction(self):
        inputs = self.data.drop(columns="ready_rating")
        full = self.ns["predict_readiness"](self.bundle, inputs)
        cutoff = pd.to_datetime(inputs["night_date"]).max() - pd.Timedelta(days=31)
        recent = inputs.loc[pd.to_datetime(inputs["night_date"]) >= cutoff]
        shortened = self.ns["predict_readiness"](self.bundle, recent)
        def latest(frame):
            return (frame.sort_values("night_date").groupby("tester_id").tail(1)
                    .sort_values("tester_id").reset_index(drop=True))
        pd.testing.assert_frame_equal(latest(full), latest(shortened), atol=1e-10, rtol=1e-10)

    def test_nested_validation_requires_multiple_people(self):
        one = self.table.loc[self.table["tester_id"] == "P01"]
        with self.assertRaises(ValueError):
            self.ns["train_ridge"](one, self.config)


if __name__ == "__main__":
    unittest.main()
