/**
 * The Muscles tab: the latest muscle tests and a way to start one, or "No muscle tests yet.". The body map, the
 * per-muscle list and recovery times wait for the recovery model. Figma "Muscles" and "Muscles, no patch sessions yet".
 */
import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Button } from '../../components/Button';
import { ListRow } from '../../components/ListRow';
import { Page } from '../../components/Page';
import { SectionHeader } from '../../components/SectionHeader';
import { Text } from '../../components/Text';
import { headingLevel } from '../../lib/a11y';
import { muscleTestSource as source } from '../../lib/muscleTestSource';
import { isDemo, scheduleFor } from '../../lib/muscleTests';
import { useSession } from '../../state/session';
import { DemoNote, ScheduleRows } from '../muscles/parts';
import { useMuscleTestsVersion } from '../muscles/useMuscleTests';

const FOOTNOTE = 'Fatigue comes from the before and after muscle tests with the EMG patch. Recovery times are '
  + 'estimates and placeholders while the team builds the model.';

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
  return (
    <Page>
      <Text variant="h1" accessibilityRole="header">Muscles</Text>
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
});
