/**
 * Where muscle tests come from. The screens only ever talk to MuscleTestSource. For now the demo source makes a
 * believable signal in code and keeps results in memory (gone on reload, nothing goes to the server). The real
 * source waits until the hardware route is picked.
 */
import {
  demoLevel, HOLD_SECONDS, LiveSample, localIso, MuscleTest, REST_SECONDS, TEST_SETUP, TestSource, TestWhen,
} from './muscleTests';

export interface MuscleTestSource {
  readonly kind: TestSource;
  connect(): Promise<void>;
  /** Plays the live signal: rest, then the hold. Stops on its own at the end. Returns a function to stop early. */
  startHold(onSample: (s: LiveSample) => void, onDone: () => void): () => void;
  /** The finished test's result. Not saved yet, the screen saves it only when the signal was good. */
  finishHold(when: TestWhen, testerId: string, workoutId: string | null): Promise<MuscleTest>;
  save(test: MuscleTest): void;
  /** Links a before test (taken from the Muscles tab) to the workout it was for. */
  link(testId: string, workoutId: string): void;
  /** Saves what the person will train on a before test, since the workout doesn't exist yet. */
  plan(testId: string, planned: { name: string; date: string }): void;
  listForWorkout(testerId: string, workoutId: string): MuscleTest[];
  listRecent(testerId: string): MuscleTest[];
}

// The one switch between the demo and a real patch. Only the demo works yet.
export const SOURCE_KIND: 'demo' | 'device' = 'demo';

// Demo results, close to the Figma examples. weakSignal lets testers see the "Signal was weak" state.
const DEMO_PCT: Record<TestWhen, number | null> = { before: null, after: 21, next_morning: 8 };
export const demoSettings = { weakSignal: false };

/** The whole test lasts the rest plus the hold, then stops by itself. */
export const TEST_MS = (REST_SECONDS + HOLD_SECONDS) * 1000;
const SAMPLE_MS = 20; // 50 a second, enough to draw

function seed(): MuscleTest[] {
  const base = { tester_id: 'demo-sam', workout_id: 'demo-legs-0929', muscle: 'quads', side: 'left' as const,
    hold_seconds: HOLD_SECONDS, ...TEST_SETUP, quality_ok: true, quality_note: null, source: 'demo' as const };
  return [
    { ...base, id: 'demo-mt-1', when: 'before', recorded_at: '2026-09-29T18:05', env_mean: 0.42, env_slope_per_s: 0.004, vs_before_pct: null },
    { ...base, id: 'demo-mt-2', when: 'after', recorded_at: '2026-09-29T19:15', env_mean: 0.51, env_slope_per_s: 0.007, vs_before_pct: 21 },
    { ...base, id: 'demo-mt-3', when: 'next_morning', recorded_at: '2026-09-30T07:50', env_mean: 0.45, env_slope_per_s: 0.005, vs_before_pct: 8 },
  ];
}

let tests: MuscleTest[] = seed();
let version = 0;
const listeners = new Set<() => void>();
const changed = () => {
  version += 1;
  listeners.forEach((l) => l());
};

export const demoSource: MuscleTestSource = {
  kind: 'demo',
  connect: async () => {},
  startHold(onSample, onDone) {
    const started = Date.now();
    const timer = setInterval(() => {
      const t_ms = Math.min(Date.now() - started, TEST_MS);
      onSample({ t_ms, level: demoLevel(t_ms, Math.random()) });
      if (t_ms >= TEST_MS) {
        clearInterval(timer);
        onDone();
      }
    }, SAMPLE_MS);
    return () => clearInterval(timer);
  },
  async finishHold(when, testerId, workoutId) {
    const pct = DEMO_PCT[when];
    const weak = demoSettings.weakSignal;
    return {
      id: `demo-mt-${Date.now().toString(36)}`, tester_id: testerId, workout_id: when === 'before' ? null : workoutId,
      when, muscle: 'quads', side: 'left', recorded_at: localIso(new Date()), hold_seconds: HOLD_SECONDS, ...TEST_SETUP,
      env_mean: 0.42 * (1 + (pct ?? 0) / 100), env_slope_per_s: 0.004, vs_before_pct: pct,
      quality_ok: !weak, quality_note: weak ? 'A flat trace with lots of noise.' : null, source: 'demo',
    };
  },
  save(test) {
    tests = [...tests.filter((t) => t.id !== test.id), test];
    changed();
  },
  link(testId, workoutId) {
    tests = tests.map((t) => (t.id === testId ? { ...t, workout_id: workoutId } : t));
    changed();
  },
  plan(testId, planned) {
    tests = tests.map((t) => (t.id === testId ? { ...t, planned } : t));
    changed();
  },
  listForWorkout: (testerId, workoutId) => tests.filter((t) => t.tester_id === testerId && t.workout_id === workoutId),
  listRecent: (testerId) =>
    tests.filter((t) => t.tester_id === testerId).sort((a, b) => b.recorded_at.localeCompare(a.recorded_at)),
};

const notConnected = () => {
  throw new Error('Not connected yet');
};
const deviceSource: MuscleTestSource = {
  kind: 'device', connect: async () => notConnected(), startHold: notConnected, finishHold: async () => notConnected(),
  save: notConnected, link: notConnected, plan: notConnected, listForWorkout: () => [], listRecent: () => [],
};

export const muscleTestSource: MuscleTestSource = SOURCE_KIND === 'demo' ? demoSource : deviceSource;

/** For useMuscleTestsVersion: screens re-render when a test is saved or linked. */
export function subscribeTests(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}
export const testsVersion = () => version;