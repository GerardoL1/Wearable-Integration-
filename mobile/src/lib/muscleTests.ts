/**
 * Layer 2 data contract: the EMG muscle tests (a 30-second wall sit before a workout, after it, and the next
 * morning) and the pure logic the screens need. No imports, so scripts/check-convert.js can test it.
 * Fatigue is how much higher the muscle signal is during the hold than in the before test.
 */
export type TestWhen = 'before' | 'after' | 'next_morning';
export type TestSource = 'demo' | 'device' | 'import';

export type MuscleTest = {
  id: string;
  tester_id: string;
  workout_id: string | null; // null for a before test not linked to a workout yet
  when: TestWhen;
  muscle: string; // like "quads"
  side: 'left' | 'right';
  recorded_at: string; // local time, "2026-09-29T18:05"
  hold_seconds: number;
  load: string;
  position: string;
  env_mean: number;
  env_slope_per_s: number;
  vs_before_pct: number | null; // null for the before test
  quality_ok: boolean;
  quality_note: string | null;
  source: TestSource;
};

export type MuscleTestSchedule = {
  before?: MuscleTest;
  after?: MuscleTest;
  next_morning?: MuscleTest;
  next_due: 'after' | 'next_morning' | null;
  next_due_by?: string; // local time, the next-morning test is due by 10 am the day after the after test
};

/** One point of the live signal while holding, about 50 a second. level is 0 to 1. */
export type LiveSample = { t_ms: number; level: number };

export const HOLD_SECONDS = 30;
export const REST_SECONDS = 5;
export const TEST_SETUP = { position: 'Wall sit, knees at 90°', load: 'Body weight' };
// A before test linked to a workout has to be from this long before it started, at most.
export const LINK_WINDOW_HOURS = 4;
const NEXT_MORNING_BY_HOUR = 10;

export const STEP: Record<TestWhen, number> = { before: 1, after: 2, next_morning: 3 };

const pad = (n: number) => String(n).padStart(2, '0');
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** "2026-09-29T18:05" for a moment, in the phone's own time zone. */
export const localIso = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const parse = (iso: string) => {
  const [date, time = '00:00'] = iso.split('T');
  const [y, m, d] = date.split('-').map(Number);
  const [h, mi] = time.split(':').map(Number);
  return new Date(y, m - 1, d, h, mi);
};

/** "6:05 pm" */
export function clockText(iso: string): string {
  const d = parse(iso);
  const h = d.getHours();
  return `${h % 12 === 0 ? 12 : h % 12}:${pad(d.getMinutes())} ${h < 12 ? 'am' : 'pm'}`;
}
/** "Mon 6:05 pm" */
export const dayClockText = (iso: string) => `${DAYS[parse(iso).getDay()]} ${clockText(iso)}`;

/** "+21%" for the big figure. */
export const pctText = (pct: number) => `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${Math.abs(Math.round(pct))}%`;
/** "21% harder" or "5% easier", for rows. */
export function harderText(pct: number): string {
  const n = Math.abs(Math.round(pct));
  return pct < 0 ? `${n}% easier` : `${n}% harder`;
}

/** The three tests of one workout in their slots, and which one comes next. The newest of each kind wins. */
export function scheduleFor(tests: MuscleTest[]): MuscleTestSchedule {
  const s: MuscleTestSchedule = { next_due: null };
  for (const t of [...tests].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at))) s[t.when] = t;
  if (!s.after) s.next_due = 'after';
  else if (!s.next_morning) {
    s.next_due = 'next_morning';
    const by = parse(s.after.recorded_at);
    by.setDate(by.getDate() + 1);
    by.setHours(NEXT_MORNING_BY_HOUR, 0, 0, 0);
    s.next_due_by = localIso(by);
  }
  return s;
}

/**
 * Before tests that could belong to a workout starting at this local time: not linked yet, and taken in the
 * hours just before it. Newest first, so the closest one is offered first.
 */
export function linkableBefore(tests: MuscleTest[], workoutStartLocal: string): MuscleTest[] {
  const start = parse(workoutStartLocal).getTime();
  return tests
    .filter((t) => t.when === 'before' && t.workout_id === null)
    .filter((t) => {
      const at = parse(t.recorded_at).getTime();
      return at <= start && start - at <= LINK_WINDOW_HOURS * 3600_000;
    })
    .sort((a, b) => b.recorded_at.localeCompare(a.recorded_at));
}

/** Only demo results carry the "Demo data, not from a sensor" line. */
export const isDemo = (tests: (MuscleTest | undefined)[]) => tests.some((t) => t?.source === 'demo');

/**
 * The fake signal for the demo: quiet during the 5 s rest, a rise when the hold starts, then a slow upward
 * drift as the muscle tires. noise is a 0 to 1 random number, passed in so tests are repeatable.
 */
export function demoLevel(t_ms: number, noise: number, drift = 0.25): number {
  const s = t_ms / 1000;
  if (s < REST_SECONDS) return 0.05 + noise * 0.04;
  const into = s - REST_SECONDS;
  const rise = Math.min(1, into / 1.5);
  return Math.min(1, 0.35 * rise + drift * (into / HOLD_SECONDS) + noise * 0.08);
}
