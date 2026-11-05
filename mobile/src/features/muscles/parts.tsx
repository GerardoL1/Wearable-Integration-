/**
 * Pieces the muscle test screens share: the live signal, the before / after / next-morning rows, and the line
 * that marks demo results.
 */
import { ReactNode, useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ListRow } from '../../components/ListRow';
import { Panel } from '../../components/Panel';
import { Text } from '../../components/Text';
import { TEST_MS } from '../../lib/muscleTestSource';
import { clockText, dayClockText, demoLevel, harderText, LiveSample, MuscleTestSchedule } from '../../lib/muscleTests';
import { useTheme } from '../../theme/theme';
import { radius } from '../../theme/tokens';

const SHOWN = 120; // about 2.4 s of signal on screen

/** The signal as a row of thin bars, newest on the right. Hidden from screen readers, the text says what it means. */
export function LiveSignal({ samples, quality = 'Good' }: { samples: LiveSample[]; quality?: string }) {
  const { colors } = useTheme();
  const recent = samples.slice(-SHOWN);
  return (
    <View style={[styles.signal, { backgroundColor: colors.surface }]}>
      <View style={styles.signalTop}>
        <Text variant="bodySmall" color="textSecondary">Signal</Text>
        <Text variant="labelSmall">{quality}</Text>
      </View>
      <View style={styles.trace} aria-hidden>
        {recent.map((s) => (
          <View key={s.t_ms} style={[styles.bar, { height: `${Math.max(4, s.level * 100)}%`, backgroundColor: colors.textPrimary }]} />
        ))}
      </View>
    </View>
  );
}

/** A looping demo signal for the screens before the test, where nothing is recorded. */
export function usePreviewSignal(): LiveSample[] {
  const [samples, setSamples] = useState<LiveSample[]>([]);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => {
      const t_ms = (Date.now() - started) % TEST_MS;
      setSamples((prev) => [...prev.slice(-SHOWN), { t_ms: Date.now() - started, level: demoLevel(t_ms, Math.random()) }]);
    }, 40);
    return () => clearInterval(timer);
  }, []);
  return samples;
}

const today = () => new Date().toDateString();
const dayOf = (iso: string) => new Date(iso).toDateString();
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Before the after test is done, the next-morning one is due the morning after the before test. */
function morningAfter(iso: string): Date {
  const d = new Date(iso);
  d.setDate(d.getDate() + 1);
  return d;
}

/** When the next-morning test is due: "Tomorrow, before 10 am" or "Tue, before 10 am". */
function dueText(d: Date): string {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  return `${d.toDateString() === tomorrow.toDateString() ? 'Tomorrow' : DAYS[d.getDay()]}, before 10 am`;
}

/**
 * The three tests in order. results shows the % on done after and next-morning rows (Workout summary, Muscles),
 * otherwise done rows say when (the saved screens). Days show once the tests span more than one day.
 */
export function ScheduleRows({ schedule: s, results, children }: {
  schedule: MuscleTestSchedule; results?: boolean; children?: ReactNode;
}) {
  const spans = !!s.next_morning || !!s.before && dayOf(s.before.recorded_at) !== today();
  const when = (iso: string) => (spans ? dayClockText(iso) : clockText(iso));
  const done = (t: NonNullable<MuscleTestSchedule['before']>) => `Done, ${when(t.recorded_at)}`;
  // With results: "21% harder to hold" after the workout, and the next morning says both when and how much.
  const after = s.after ? (results && s.after.vs_before_pct !== null ? `${harderText(s.after.vs_before_pct)} to hold`
    : done(s.after)) : results ? 'Not done' : s.next_due === 'after' ? 'Next' : null;
  const morning = s.next_morning && results && s.next_morning.vs_before_pct !== null
    ? `${done(s.next_morning)} · ${harderText(s.next_morning.vs_before_pct)}` : s.next_morning ? done(s.next_morning) : null;
  return (
    <Panel>
      <ListRow label="Before your workout"
        value={s.before ? `${s.before.planned ? `${s.before.planned.name} · ` : ''}${done(s.before)}` : 'Not done'} />
      <ListRow label="After your workout" value={after} />
      <ListRow label="Next morning"
        value={morning ?? (s.next_due_by ? dueText(new Date(s.next_due_by))
          : s.before ? dueText(morningAfter(s.before.recorded_at)) : null)} />
      {children}
    </Panel>
  );
}

/** Shown under every result while the demo source is on. Gone once results come from a real sensor. */
export function DemoNote({ show }: { show: boolean }) {
  return show ? <Text variant="bodySmall" color="textSecondary" style={styles.demo}>Demo data, not from a sensor</Text> : null;
}

const styles = StyleSheet.create({
  signal: { borderRadius: radius.md, padding: 16, gap: 12 },
  signalTop: { flexDirection: 'row', justifyContent: 'space-between' },
  trace: { height: 64, flexDirection: 'row', alignItems: 'flex-end', gap: 1, overflow: 'hidden' },
  bar: { flex: 1, minWidth: 1, borderRadius: 1 },
  demo: { marginTop: 8 },
});
