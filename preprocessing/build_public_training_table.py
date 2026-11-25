"""
Build one training table from the public wearable datasets, plus a coverage summary of who is in it.

    python build_public_training_table.py --data C:\\Users\\you\\Documents\\readiness-data
        --finnish C:\\Users\\you\\Downloads\\doi_10_5061_dryad_qz612jmrn__v20251128.zip
        --uci C:\\Users\\you\\Downloads\\doi_10_7280_D1WH6T__v20240104.zip

The --data folder holds what was downloaded as is:
    pmdata/pmdata/p01 ... p16 and participant-overview.xlsx     (OSF vx4bk)
    lifesnaps/rais_anonymized.zip                               (Zenodo 7229547)
    fatigue_zenodo/day_activity_features.csv and the surveys    (Zenodo 8018238)
A dataset that isn't there is skipped. The table and summary are written to --out (default: the --data
folder). That's other people's health data, so it's refused inside the repo, like export_training_table.py.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import public_datasets as D

REPO = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser(description="Build the training table from public wearable datasets.")
parser.add_argument("--data", required=True, type=Path, help="folder with pmdata/, lifesnaps/ and fatigue_zenodo/")
parser.add_argument("--finnish", type=Path, help="Dryad zip of the Finnish immigrants study")
parser.add_argument("--uci", type=Path, help="Dryad zip of the UC Irvine students study")
parser.add_argument("--out", type=Path, help="folder for the table and summary (default: --data)")
args = parser.parse_args()

out = (args.out or args.data).resolve()
if out == REPO or REPO in out.parents:
    sys.exit("Write the table outside the repo folder. It's other people's health data and mustn't go into git.")

sources = {
    "PMData": (args.data / "pmdata" / "pmdata", D.pmdata),
    "LifeSnaps": (args.data / "lifesnaps" / "rais_anonymized.zip", D.lifesnaps),
    "fatigue study": (args.data / "fatigue_zenodo", D.fatigue_study),
    "Finnish immigrants": (args.finnish, D.finnish_immigrants),
    "UC Irvine students": (args.uci, D.uci_students),
}
parts = []
for name, (path, read) in sources.items():
    if path is None or not path.exists():
        print(f"{name}: skipped (not found)")
        continue
    t = read(path)
    print(f"{name}: {t['person_id'].nunique()} people, {len(t)} nights", flush=True)
    parts.append(t)
if not parts:
    sys.exit("No datasets found. Check --data, --finnish and --uci.")

table = pd.concat(parts, ignore_index=True)
# Days with no sleep or HRV at all are noise for training.
table = table[table["tst_min"].notna() | table["hrv_night_ms"].notna()].reset_index(drop=True)
out.mkdir(parents=True, exist_ok=True)
table.to_csv(out / "training_table_public.csv", index=False)

people = table.drop_duplicates("person_id")
age = pd.to_numeric(people["age"], errors="coerce")
summary = {
    "rows": len(table),
    "people": len(people),
    "people_by_source": people["source"].value_counts().to_dict(),
    "nights_by_source": table["source"].value_counts().to_dict(),
    "nights_by_device": table["device"].value_counts().to_dict(),
    "nights_with_hrv": int(table["hrv_night_ms"].notna().sum()),
    "nights_with_z_hrv": int(table["z_hrv"].notna().sum()),
    "nights_with_z_rhr": int(table["z_rhr"].notna().sum()),
    "labels": {
        "real readiness 1-10 (PMData)": int(table.get("checkin_ready_to_train", pd.Series()).notna().sum()),
        "tired yesterday 0-4 (fatigue study)": int(table.get("fatigue_tired_yesterday", pd.Series()).notna().sum()),
    },
    "people_by_gender": people["gender"].fillna("unknown").value_counts().to_dict(),
    "people_by_age_band": people["age_band"].fillna("unknown").value_counts().to_dict(),
    "people_by_exact_age": pd.cut(age, [0, 29, 39, 49, 59, 120], labels=["<30", "30s", "40s", "50s", "60+"])
    .value_counts(sort=False)
    .to_dict(),
    "known_gaps": [
        "no Apple Watch data, and no SDNN (every HRV here is RMSSD)",
        "real readiness labels only from the 16 PMData people",
        "BMI mostly missing",
        "no one from Africa or Oceania, few over 70",
    ],
}
(out / "training_table_public_coverage.json").write_text(json.dumps(summary, indent=2, default=str))
print(json.dumps(summary, indent=2, default=str))
print("written", out / "training_table_public.csv")
