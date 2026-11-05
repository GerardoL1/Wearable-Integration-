/**
 * A muscle test: get ready, hold for 30 seconds, then the result. The same screen does the before, after and
 * next-morning tests, only the step, the words and the result change. Figma "Muscle test, ...".
 * Before tests aren't linked to a workout (it usually doesn't exist yet). Workout summary links them later.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { ReactNode, useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, StyleSheet, View } from 'react-native';

import { Button } from '../../components/Button';
import { ListRow } from '../../components/ListRow';
import { LiveText } from '../../components/LiveText';
import { Notice } from '../../components/Notice';
import { Page } from '../../components/Page';
import { Panel } from '../../components/Panel';
import { Chips } from '../../components/Editors';
import { ProgressBar } from '../../components/ProgressBar';
import { StepBar } from '../../components/SetupFrame';
import { Text } from '../../components/Text';
import { demoSettings, muscleTestSource as source } from '../../lib/muscleTestSource';
import {
  HOLD_SECONDS, LiveSample, MuscleTest, pctText, REST_SECONDS, scheduleFor, STEP, TEST_SETUP, TestWhen,
} from '../../lib/muscleTests';
import { dateValue, WORKOUT_PICKS } from '../../lib/logWorkout';
import { useSession } from '../../state/session';
import { DateTimeField } from '../train/DateTimeField';
import { Box } from '../train/LogWorkoutScreen';
import { DemoNote, LiveSignal, ScheduleRows, usePreviewSignal } from './parts';
import { useMuscleTestsVersion } from './useMuscleTests';

const TITLE: Record<TestWhen, string> = { before: 'Before your workout', after: 'After your workout', next_morning: 'The next morning' };
const INTRO: Record<TestWhen, string> = {
  before: 'A 30-second hold shows how fresh your quads are. Do it after your warm-up.',
  after: 'The same hold as before your workout. Do it within 5 minutes of your last set.',
  next_morning: 'The same hold again, before 10 am, to see how your quads recovered.',
};

const clock = (seconds: number) => `0:${String(Math.max(0, Math.ceil(seconds))).padStart(2, '0')}`;

/** Fades its content in over 200 ms when it first shows, or shows it at once when the phone asks for less motion. */
function FadeIn({ children }: { children: ReactNode }) {
  const [opacity] = useState(() => new Animated.Value(0));
  useEffect(() => {
    let anim: Animated.CompositeAnimation | null = null;
    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (reduce) opacity.setValue(1);
      else (anim = Animated.timing(opacity, { toValue: 1, duration: 200, useNativeDriver: true })).start();
    });
    return () => anim?.stop();
  }, [opacity]);
  return <Animated.View style={{ opacity }}>{children}</Animated.View>;
}

export default function MuscleTestScreen() {
  const { userId } = useSession();
  const params = useLocalSearchParams<{ when?: string; workoutId?: string; weak?: string }>();
  const when: TestWhen = params.when === 'after' || params.when === 'next_morning' ? params.when : 'before';
  const workoutId = params.workoutId ?? null;
  useMuscleTestsVersion();

  const [phase, setPhase] = useState<'ready' | 'holding' | 'done' | 'plan'>('ready');
  // The plan step after a before test: only what and when, since times and sweat come after training.
  const [planName, setPlanName] = useState('');
  const [planDate, setPlanDate] = useState(() => dateValue(new Date()));
  const [planError, setPlanError] = useState<string | null>(null);
  const [samples, setSamples] = useState<LiveSample[]>([]);
  const [result, setResult] = useState<MuscleTest | null>(null);
  const stop = useRef<(() => void) | null>(null);
  const preview = usePreviewSignal();
  useEffect(() => () => stop.current?.(), []);

  function start() {
    // Demo only: "&weak=1" in the address forces a weak signal, so testers can see that state.
    demoSettings.weakSignal = source.kind === 'demo' && params.weak === '1';
    setSamples([]);
    setResult(null);
    setPhase('holding');
    stop.current = source.startHold((s) => setSamples((prev) => [...prev.slice(-150), s]), async () => {
      const test = await source.finishHold(when, userId, workoutId);
      // A weak signal gives a number nobody should trust, so it isn't saved.
      if (test.quality_ok) source.save(test);
      setResult(test);
      setPhase('done');
    });
  }
  function cancel() {
    stop.current?.();
    setPhase('ready');
  }
  const leave = (to: Parameters<typeof router.replace>[0]) => (router.canGoBack() ? router.back() : router.replace(to));

  const step = `Muscle test · ${STEP[when]} of 3`;

  if (phase === 'holding') {
    const t = samples.length ? samples[samples.length - 1].t_ms / 1000 : 0;
    const resting = t < REST_SECONDS;
    const left = resting ? REST_SECONDS - t : REST_SECONDS + HOLD_SECONDS - t;
    return (
      <Page>
        <View style={styles.column}>
        <StepBar label={step} step={STEP[when]} />
        {/* Keyed, so the hold fades in when the rest ends, with no tap needed. */}
        <FadeIn key={resting ? 'rest' : 'hold'}>
          <Text variant="greeting" accessibilityRole="header">{resting ? 'Rest first' : 'Hold still'}</Text>
          <Text variant="body" color="textSecondary" style={styles.space8}>
            {resting ? 'Stay relaxed. The hold starts in a moment.' : 'Keep your knees at 90° and breathe normally.'}
          </Text>
          <View style={styles.space24}>
            <Text variant="bodySmall" color="textSecondary">{resting ? 'Hold starts in' : 'Time left'}</Text>
            <LiveText variant="scoreMetric">{clock(left)}</LiveText>
            {resting ? null : (
              <>
                <View style={styles.space8}>
                  <ProgressBar share={Math.min(1, (t - REST_SECONDS) / HOLD_SECONDS)} />
                </View>
                <View style={styles.ends}>
                  <Text variant="bodySmall" color="textSecondary">0:00</Text>
                  <Text variant="bodySmall" color="textSecondary">{clock(HOLD_SECONDS)}</Text>
                </View>
              </>
            )}
          </View>
        </FadeIn>
        <View style={styles.space24}><LiveSignal samples={samples} /></View>
        {resting ? null : (
          <Text variant="bodySmall" color="textSecondary" style={styles.space12}>The test stops on its own after 30 seconds.</Text>
        )}
        <Button title="Stop the test" kind="text" style={styles.space24} onPress={cancel} />
      </View>
      </Page>
    );
  }

  if (phase === 'done' && result && !result.quality_ok) {
    return (
      <Page>
        <View style={styles.column}>
        <StepBar label={step} step={STEP[when]} />
        <Text variant="greeting" accessibilityRole="header">{TITLE[when]}</Text>
        <Text variant="body" color="textSecondary" style={styles.space8}>{INTRO[when]}</Text>
        <View style={styles.space16}>
          <Notice type="warning" label="Signal was weak" live
            action={{ label: 'Try the test again', onPress: () => setPhase('ready') }}>
            {`${result.quality_note ?? 'The signal was too weak to measure.'} Press the patch down firmly, then try again. This test wasn't saved.`}
          </Notice>
        </View>
        <DemoNote show={result.source === 'demo'} />
        <View style={styles.actions}>
          <Button title="Skip this test" kind="text" onPress={() => leave(workoutId
            ? { pathname: '/train/workout/[workoutId]', params: { workoutId } } : '/muscles')} />
        </View>
      </View>
      </Page>
    );
  }

  if (phase === 'plan' && result) {
    function goTrain() {
      if (!planName.trim()) return setPlanError('Type a name for the workout.');
      source.plan(result!.id, { name: planName.trim(), date: planDate });
      router.replace('/train');
    }
    const picked = WORKOUT_PICKS.includes(planName) ? planName : null;
    return (
      <Page>
        <View style={styles.column}>
          <StepBar label={step} step={STEP[when]} />
          <Text variant="greeting" accessibilityRole="header">What are you training?</Text>
          <Text variant="body" color="textSecondary" style={styles.space8}>
            So your before test finds its workout later. Times come from your watch, or you add them after.
          </Text>
          <View style={[styles.space24, styles.fields]}>
            <View style={styles.fields}>
              <Box id="plan-name" label="Workout" spoken="Workout name" value={planName} placeholder="e.g. Leg day"
                error={planError ?? undefined} editable onChange={(v) => {
                  setPlanName(v);
                  setPlanError(null);
                }} />
              <Chips name="Quick picks" options={WORKOUT_PICKS.map((p) => ({ value: p, label: p }))} value={picked}
                onPick={(p) => {
                  setPlanName(p);
                  setPlanError(null);
                }} />
              {planError ? <LiveText error nativeID="plan-name-error" variant="bodySmall" color="low">{planError}</LiveText> : null}
            </View>
            <DateTimeField id="plan-date" label="Date" mode="date" value={planDate} onChange={setPlanDate} />
          </View>
          <View style={styles.actions}>
            <Button title="Go train" onPress={goTrain} />
            <Button title="Skip" kind="text" onPress={() => router.replace('/train')} />
          </View>
        </View>
      </Page>
    );
  }

  if (phase === 'done' && result) {
    const schedule = scheduleFor(
      result.workout_id ? source.listForWorkout(userId, result.workout_id) : [result],
    );
    const pct = result.vs_before_pct;
    const title = when === 'before' ? 'Before test saved' : when === 'after' ? 'Your quads are tired' : 'Quads are recovering';
    const intro = when === 'before'
      ? 'Go train. Come back for the after test within 5 minutes of your last set.'
      : when === 'after'
        ? `They worked ${pct}% harder to hold the same position than before your workout.`
        : `Down from ${pctText(schedule.after?.vs_before_pct ?? 0)} right after your workout. They're ready again when this is back near 0%.`;
    return (
      <Page>
        <View style={styles.column}>
        <StepBar label={step} step={STEP[when]} />
        <Text variant="greeting" accessibilityRole="header">{title}</Text>
        <Text variant="body" color="textSecondary" style={styles.space8}>{intro}</Text>
        {pct !== null ? (
          <View style={styles.space24}>
            <Text variant="bodySmall" color="textSecondary">{when === 'after' ? 'After vs before' : 'This morning vs before'}</Text>
            <Text variant="scoreMetric">{pctText(pct)}</Text>
          </View>
        ) : null}
        <View style={styles.space24}><ScheduleRows schedule={schedule} /></View>
        <DemoNote show={result.source === 'demo'} />
        <View style={styles.actions}>
          {when === 'before' ? (
            <>
              <Button title="Start a workout" onPress={() => setPhase('plan')} />
              <Button title="Back to Today" kind="text" onPress={() => router.replace('/today')} />
            </>
          ) : (
            <>
              <Button title="Done" onPress={() => leave(workoutId
                ? { pathname: '/train/workout/[workoutId]', params: { workoutId } } : '/muscles')} />
              {when === 'after' && workoutId ? (
                <Button title="Add sweat data" kind="text"
                  onPress={() => router.replace({ pathname: '/train/import', params: { workoutId } })} />
              ) : null}
            </>
          )}
        </View>
      </View>
      </Page>
    );
  }

  return (
    <Page>
        <View style={styles.column}>
      <StepBar label={step} step={STEP[when]} />
      <Text variant="greeting" accessibilityRole="header">{TITLE[when]}</Text>
      <Text variant="body" color="textSecondary" style={styles.space8}>{INTRO[when]}</Text>
      <View style={styles.space24}><LiveSignal samples={preview} /></View>
      <Text variant="bodySmall" color="textSecondary" style={styles.space12}>
        Rest for 5 seconds, then hold still until the timer ends.
      </Text>
      <Panel style={styles.space16}>
        <ListRow label="Position" value={TEST_SETUP.position} />
        <ListRow label="Load" value={TEST_SETUP.load} />
        <ListRow label="Patch" value="Left quads, marked spot" />
        <ListRow label="Hold" value={`${HOLD_SECONDS} seconds`} />
      </Panel>
      <View style={styles.actions}>
        <Button title="Start the hold" onPress={start} />
        <Button title="Skip this test" kind="text" onPress={() => leave(workoutId
          ? { pathname: '/train/workout/[workoutId]', params: { workoutId } } : '/muscles')} />
      </View>
    </View>
      </Page>
  );
}

const styles = StyleSheet.create({
  // One readable column on the computer, like the forms.
  column: { maxWidth: 560 },
  space8: { marginTop: 8 },
  space12: { marginTop: 12 },
  space16: { marginTop: 16 },
  space24: { marginTop: 24 },
  ends: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
  actions: { marginTop: 28, gap: 12 },
  fields: { gap: 18 },
});
