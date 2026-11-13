/**
 * Where muscle tests come from. The screens only ever talk to muscleTestSource, which is the demo or the USB
 * sensor depending on the switch. The demo makes a believable signal in code and keeps results in memory (gone on
 * reload, nothing goes to the server). The USB source is in usbMuscleTestSource.ts.
 */
import {
  demoLevel, HOLD_SECONDS, LiveSample, localIso, MuscleTest, REST_SECONDS, TEST_SETUP, TestSource, TestWhen,
} from './muscleTests';
import { makeUsbSource } from './usbMuscleTestSource';

export interface MuscleTestSource {
  readonly kind: TestSource;
  /** False where a test can't be recorded, like the USB sensor on the iPhone. Results still show. */
  readonly canRecord: boolean;
  readonly connected: boolean;
  /** Throws when it couldn't connect. */
  connect(): Promise<void>;
  /**
   * Plays the live signal: rest, then the hold. Stops on its own at the end. onLost is called instead of onDone
   * when the sensor goes away mid-test. Returns a function to stop early.
   */
  startHold(onSample: (s: LiveSample) => void, onDone: () => void, onLost?: () => void): () => void;
  /** The finished test's result. The demo doesn't keep it yet, the screen saves it only when the signal was good. */
  finishHold(when: TestWhen, testerId: string, workoutId: string | null): Promise<MuscleTest>;
  save(test: MuscleTest): Promise<void>;
  /** Links a before test (taken from the Muscles tab) to the workout it was for. */
  link(testId: string, workoutId: string): Promise<void>;
  /** Saves what the person will train on a before test, since the workout doesn't exist yet. */
  plan(testId: string, planned: { name: string; date: string }): Promise<void>;
  /** Fetches the tester's tests again, where they're kept somewhere else. */
  refresh(testerId: string): Promise<void>;
  listForWorkout(testerId: string, workoutId: string): MuscleTest[];
  listRecent(testerId: string): MuscleTest[];
}

export type SourceChoice = 'demo' | 'usb';

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
  canRecord: true,
  connected: true,
  connect: async () => {},
  refresh: async () => {},
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
  async save(test) {
    tests = [...tests.filter((t) => t.id !== test.id), test];
    changed();
  },
  async link(testId, workoutId) {
    tests = tests.map((t) => (t.id === testId ? { ...t, workout_id: workoutId } : t));
    changed();
  },
  async plan(testId, planned) {
    tests = tests.map((t) => (t.id === testId ? { ...t, planned } : t));
    changed();
  },
  listForWorkout: (testerId, workoutId) => tests.filter((t) => t.tester_id === testerId && t.workout_id === workoutId),
  listRecent: (testerId) =>
    tests.filter((t) => t.tester_id === testerId).sort((a, b) => b.recorded_at.localeCompare(a.recorded_at)),
};

export const usbSource = makeUsbSource(changed);

// The switch between the demo and the USB sensor. useMuscleTestsVersion keeps the choice between visits.
let choice: SourceChoice = 'demo';
export const sourceChoice = () => choice;
export function setSourceChoice(c: SourceChoice) {
  if (c === choice) return;
  choice = c;
  changed();
}
const current = () => (choice === 'usb' ? usbSource : demoSource);

/** What the screens use: whichever source the switch picked, at the moment of each call. */
export const muscleTestSource: MuscleTestSource = {
  get kind() {
    return current().kind;
  },
  get canRecord() {
    return current().canRecord;
  },
  get connected() {
    return current().connected;
  },
  connect: () => current().connect(),
  startHold: (onSample, onDone, onLost) => current().startHold(onSample, onDone, onLost),
  finishHold: (when, testerId, workoutId) => current().finishHold(when, testerId, workoutId),
  save: (test) => current().save(test),
  link: (testId, workoutId) => current().link(testId, workoutId),
  plan: (testId, planned) => current().plan(testId, planned),
  refresh: (testerId) => current().refresh(testerId),
  listForWorkout: (testerId, workoutId) => current().listForWorkout(testerId, workoutId),
  listRecent: (testerId) => current().listRecent(testerId),
};

/** For useMuscleTestsVersion: screens re-render when a test is saved or linked. */
export function subscribeTests(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}
export const testsVersion = () => version;