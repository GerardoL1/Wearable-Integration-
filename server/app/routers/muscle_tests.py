"""
Muscle tests (Layer 2): upload one test's raw samples from the USB sensor, list a person's tests, and link a
before test to its workout or save what they plan to train. The work is in app/services/muscle_tests.py.
"""

from fastapi import APIRouter, Query

from app.core.urls import USER
from app.schemas.muscle_tests import MuscleTest, MuscleTestChange, MuscleTestUpload
from app.services import muscle_tests

router = APIRouter(prefix=USER, tags=["muscle tests"])


@router.post("/muscle-tests", response_model=MuscleTest)
def upload_muscle_test(user_id: str, body: MuscleTestUpload):
    """Stores the raw samples and the result, good or not. quality_ok and quality_note say which."""
    return muscle_tests.save_upload(user_id, body)


@router.get("/muscle-tests", response_model=list[MuscleTest])
def list_muscle_tests(user_id: str, workout_id: str | None = Query(None, max_length=80)):
    return muscle_tests.list_tests(user_id, workout_id)


@router.patch("/muscle-tests/{test_id}", response_model=MuscleTest)
def change_muscle_test(user_id: str, test_id: str, body: MuscleTestChange):
    return muscle_tests.change(user_id, test_id, body)
