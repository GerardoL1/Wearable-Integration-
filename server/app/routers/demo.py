"""Demo mode (temporary, remove later): load one of the mock people with a fixed clock."""

from typing import Literal

from fastapi import APIRouter

from app.core import db
from app.core.urls import API_V1
from app.schemas.processing import DemoUser
from app.services import processing
from app.services.apple_export import import_export
from layer1.samples import sample_path

router = APIRouter(prefix=API_V1, tags=["demo"])

# The mock people last sleep on the night of 30 Sep 2026 (they wake on 1 Oct), so the demo
# clock sits just after that night's update time.
DEMO_CLOCK = "2026-10-01T08:30:00"
# A filled-in profile, so Today greets them by name and Profile isn't empty in a demo.
DEMO_PROFILES = {"sam": ("Sam", 31, 72.0), "alex": ("Alex", 27, 81.0), "jordan": ("Jordan", 38, 64.0)}


@router.post("/demo-users/{person}", response_model=DemoUser)
def load_demo(person: Literal["sam", "alex", "jordan"]):
    """Load a mock person as demo-<name> with a fixed clock. Reloading starts them fresh."""
    user_id = f"demo-{person}"
    with db.connect() as conn:
        # The raw samples are kept by test id, so they go before the tests that point to them.
        conn.execute(
            "DELETE FROM muscle_test_samples WHERE test_id IN (SELECT id FROM muscle_tests WHERE user_id = ?)",
            (user_id,),
        )
        for table in (
            "samples",
            "sleep_stages",
            "nights",
            "runs",
            "readiness_snapshots",
            "checkins",
            "explanation_feedback",
            "workouts",
            "sweat_sessions",
            "sweat_minutes",
            "muscle_tests",
            "users",
        ):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        name, age, weight_kg = DEMO_PROFILES[person]
        conn.execute(
            "INSERT INTO users (user_id, clock_local, name, age, weight_kg) VALUES (?, ?, ?, ?, ?)",
            (user_id, DEMO_CLOCK, name, age, weight_kg),
        )
        import_export(sample_path(person), conn, user_id)
    processing.process_user(user_id, force=True)
    return {"user_id": user_id, "clock_local": DEMO_CLOCK}
