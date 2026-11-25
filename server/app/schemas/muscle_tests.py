"""Muscle tests (Layer 2): one 30-second wall sit recorded by the USB sensor, uploaded raw and processed here."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

When = Literal["before", "after", "next_morning"]
Side = Literal["left", "right"]
Text = Annotated[str, Field(min_length=1, max_length=80)]
LocalMinute = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")]
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")]


class MuscleTestUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Id  # made by the app, so a Save sent twice doesn't store the test twice
    when: When
    muscle: Text
    side: Side
    recorded_at: LocalMinute  # the phone's local time when the test started
    load: Text
    position: Text
    patch_spot: Text
    device: Text
    gain_note: Annotated[str, Field(max_length=200)] | None = None
    workout_id: Id | None = None
    before_test_id: Id | None = None  # the before test an after or next-morning test compares to
    # The raw sensor stream: Arduino micros() and the 10-bit reading, one pair per sample.
    time_us: list[int]
    adc: list[int]


class Planned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=60)]
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class MuscleTestChange(BaseModel):
    """Only the fields sent are changed. Send null to clear one."""

    model_config = ConfigDict(extra="forbid")

    workout_id: Id | None = None
    planned: Planned | None = None


class SignalStats(BaseModel):
    sample_rate_hz: float
    gap_share: float  # share of steps between samples longer than 3 ms
    clip_share: float  # share of samples at the top of the range
    adc_min: int
    adc_max: int
    baseline_adc: float
    hold_start_s: float | None  # from the first sample, None when no hold was found
    hold_end_s: float | None


class MuscleTest(BaseModel):
    """Same shape as MuscleTest in mobile/src/lib/muscleTests.ts, plus what the sensor check needs."""

    id: str
    tester_id: str
    workout_id: str | None
    when: When
    muscle: str
    side: Side
    recorded_at: str
    hold_seconds: float
    load: str
    position: str
    patch_spot: str
    device: str
    gain_note: str | None
    env_mean: float  # ADC counts above the resting baseline
    env_slope_per_s: float
    vs_before_pct: float | None
    quality_ok: bool
    quality_note: str | None
    source: Literal["device"] = "device"
    planned: Planned | None
    stats: SignalStats
