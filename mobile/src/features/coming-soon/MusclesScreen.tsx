/**
 * The Muscles tab: how the tested muscle is recovering, the latest muscle tests and a way to start one, or
 * "No muscle tests yet.". Recovery follows a placeholder rule (lib/muscleTests.ts recoveryOf) until the model
 * exists. Untested muscles need logged exercises, so they show as not tested. Figma "Muscles".
 */
import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { BodyMap } from '../../components/BodyMap';
import { Button } from '../../components/Button';
import { ListRow } from '../../components/ListRow';
import { Page } from '../../components/Page';
import { Panel } from '../../components/Panel';
import { SectionHeader } from '../../components/SectionHeader';
import { Text } from '../../components/Text';
import { headingLevel } from '../../lib/a11y';
import { muscleTestSource as source } from '../../lib/muscleTestSource';
import { dayClockText, harderText, isDemo, readyText, recoveryOf, scheduleFor } from '../../lib/muscleTests';
import { useSession } from '../../state/session';
import { DemoNote, ScheduleRows } from '../muscles/parts';
import { useMuscleTestsVersion } from '../muscles/useMuscleTests';

const FOOTNOTE = 'Fatigue comes from the before and after muscle tests with the EMG patch. Recovery times are '
  + 'estimates and placeholders while the team builds the model.';
const HEADLINE = { fatigued: 'Your quads are still tired.', recovering: 'Your quads are still recovering.',
  ready: 'Your quads are ready.' };
const LEVEL = { fatigued: 'Fatigued', recovering: 'Recovering', ready: 'Ready' };

export default function MusclesScreen() {
  const { userId } = useSession();
  useMuscleTestsVersion();
  const latest = source.listRecent(userId)[0];
  const start = () => router.push('/muscles/setup');

  if (!latest) {
    return (
      <Page>
        <Text variant="h1" accessibilityRole="header">Muscles</Text>
        <Text variant="greeting" accessibilityRole="header" {...headingLevel(2)} style={styles.title}>
          No muscle tests yet.
        </Text>
        <Text variant="body" color="textSecondary" style={styles.text}>
          Do a 30-second muscle test before and after a workout, and again the next morning, to see how each muscle
          is recovering. Muscles you don’t test show up here as estimates.
        </Text>
        <View style={styles.actions}><Button title="Start a muscle test" onPress={start} /></View>
        <Text variant="bodySmall" color="textSecondary" style={styles.note}>{FOOTNOTE}</Text>
      </Page>
    );
  }

  // The newest test and the ones linked to the same workout. A before test on its own waits for its workout.
  const tests = latest.workout_id ? source.listForWorkout(userId, latest.workout_id) : [latest];
  const schedule = scheduleFor(tests);
  const now = new Date();
  const r = recoveryOf(schedule, now);
  return (
    <Page>
      <Text variant="h1" accessibilityRole="header">Muscles</Text>
      {r ? (
        <View style={styles.title}>
          <Text variant="greeting" accessibilityRole="header" {...headingLevel(2)}>{HEADLINE[r.level]}</Text>
          <Text variant="body" color="textSecondary" style={styles.text}>
            {`Your last muscle test, ${dayClockText(r.tested_at)}, was ${harderText(r.pct)} to hold than before your workout.`}
          </Text>
          <View style={styles.section}><BodyMap levels={{ quads: r.level }} /></View>
          <View style={styles.section}>
            <SectionHeader title="By muscle" note="Ready again" />
            <Panel>
              <ListRow label="Quads" value={r.level === 'ready' ? 'Ready now' : `${LEVEL[r.level]} · ${readyText(r, now)}`}
                valueColor={r.level === 'fatigued' ? 'moderate' : r.level === 'ready' ? 'ready' : undefined} />
              <ListRow label="Other muscles" value="Not tested" />
            </Panel>
          </View>
        </View>
      ) : null}
      <View style={styles.title}>
        <SectionHeader title="Muscle tests" />
        <ScheduleRows schedule={schedule} results>
          <ListRow label="Start a muscle test" onPress={start} />
        </ScheduleRows>
        <DemoNote show={isDemo(tests)} />
      </View>
      <Text variant="bodySmall" color="textSecondary" style={styles.note}>{FOOTNOTE}</Text>
    </Page>
  );
}

const styles = StyleSheet.create({
  title: { marginTop: 28, maxWidth: 520 },
  text: { marginTop: 8, maxWidth: 520 },
  actions: { marginTop: 24, maxWidth: 520 },
  note: { marginTop: 16, maxWidth: 520 },
  section: { marginTop: 24 },
});
