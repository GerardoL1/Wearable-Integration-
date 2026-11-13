/**
 * Muscle tests from the USB sensor. The hold is recorded raw from the Arduino, uploaded to the server, which
 * works out the numbers and keeps them. The tests are kept here too, so the screens can read them straight away,
 * and fetched again from the server when a screen opens (that's how the iPhone sees results recorded on the computer).
 */
import { HOLD_SECONDS, localIso, MuscleTest, REST_SECONDS, TEST_SETUP, TestWhen } from './muscleTests';
import type { MuscleTestSource } from './muscleTestSource';
import { ADC_MAX, connectUsb, hasWebSerial, onUsbSamples, onUsbState, RawSample, usbState } from './usbSerial';

const TEST_US = (REST_SECONDS + HOLD_SECONDS) * 1e6;
const DRAW_EVERY_US = 20_000; // 50 points a second is enough to draw
const SILENT_MS = 1500; // no samples for this long during a test counts as a lost sensor

export const PATCH_SPOT = 'Left quads, marked spot';
export const DEVICE = 'Muscle Sensor V3';

export const usbServer = { url: '' };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(usbServer.url.replace(/\/$/, '') + path, {
    ...init, headers: { 'Content-Type': 'application/json' },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail : `The server said ${res.status}.`);
  }
  return body as T;
}
const testsUrl = (testerId: string) => `/api/v1/users/${encodeURIComponent(testerId)}/muscle-tests`;

export function makeUsbSource(changed: () => void): MuscleTestSource {
  let tests: MuscleTest[] = [];
  // The recording in progress or just finished, waiting for finishHold.
  let recorded: RawSample[] = [];
  let startedAt = '';

  const put = (t: MuscleTest) => {
    tests = [...tests.filter((x) => x.id !== t.id), t];
    changed();
  };
  const patch = async (testerId: string, testId: string, body: object) =>
    put(await call<MuscleTest>(`${testsUrl(testerId)}/${encodeURIComponent(testId)}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }));

  return {
    kind: 'device',
    get canRecord() {
      return hasWebSerial();
    },
    get connected() {
      return usbState() === 'connected';
    },
    connect: async () => {
      const s = await connectUsb(true);
      if (s !== 'connected') throw new Error(s);
    },
    startHold(onSample, onDone, onLost) {
      recorded = [];
      startedAt = localIso(new Date());
      let first: number | null = null;
      let nextDraw = 0;
      let heard = Date.now();
      let finished = false;
      const end = (lost: boolean) => {
        if (finished) return;
        finished = true;
        stopSamples();
        stopState();
        clearInterval(watchdog);
        if (lost) onLost?.();
        else onDone();
      };
      const stopSamples = onUsbSamples((batch) => {
        heard = Date.now();
        for (const s of batch) {
          if (first === null) first = s.t_us;
          const t_us = s.t_us - first;
          if (t_us > TEST_US) return end(false);
          recorded.push(s);
          if (t_us >= nextDraw) {
            nextDraw = t_us + DRAW_EVERY_US;
            onSample({ t_ms: t_us / 1000, level: s.adc / ADC_MAX });
          }
        }
      });
      const stopState = onUsbState(() => {
        if (usbState() !== 'connected') end(true);
      });
      const watchdog = setInterval(() => {
        if (Date.now() - heard > SILENT_MS) end(true);
      }, 250);
      if (usbState() !== 'connected') end(true);
      return () => {
        finished = true;
        stopSamples();
        stopState();
        clearInterval(watchdog);
      };
    },
    async finishHold(when: TestWhen, testerId: string, workoutId: string | null) {
      const body = {
        id: `usb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
        when, muscle: 'quads', side: 'left', recorded_at: startedAt, ...TEST_SETUP, patch_spot: PATCH_SPOT,
        device: DEVICE, gain_note: null, workout_id: when === 'before' ? null : workoutId,
        time_us: recorded.map((s) => s.t_us), adc: recorded.map((s) => s.adc),
      };
      return call<MuscleTest>(testsUrl(testerId), { method: 'POST', body: JSON.stringify(body) });
    },
    // The server stored it when it was processed, so this only adds it to the list here.
    async save(test) {
      put(test);
    },
    async link(testId, workoutId) {
      const t = tests.find((x) => x.id === testId);
      if (t) await patch(t.tester_id, testId, { workout_id: workoutId });
    },
    async plan(testId, planned) {
      const t = tests.find((x) => x.id === testId);
      if (t) await patch(t.tester_id, testId, { planned });
    },
    async refresh(testerId) {
      if (!usbServer.url || !testerId) return;
      const fresh = await call<MuscleTest[]>(testsUrl(testerId));
      tests = [...tests.filter((t) => t.tester_id !== testerId), ...fresh];
      changed();
    },
    listForWorkout: (testerId, workoutId) => tests.filter((t) => t.tester_id === testerId && t.workout_id === workoutId),
    listRecent: (testerId) =>
      tests.filter((t) => t.tester_id === testerId).sort((a, b) => b.recorded_at.localeCompare(a.recorded_at)),
  };
}
