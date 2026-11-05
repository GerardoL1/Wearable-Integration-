/**
 * Workout summary's "Muscle tests" section. With tests: fatigue, the before / after / next-morning rows and the
 * next test to do. Without: "Add muscle tests", which links the before test taken from the Muscles tab (the
 * workout didn't exist yet then) and opens the after test. The design tab's written spec, until Figma has frames.
 */
import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '../../components/Button';
import { Notice } from '../../components/Notice';
import { SectionHeader } from '../../components/SectionHeader';
import { Text } from '../../components/Text';
import { muscleTestSource as source } from '../../lib/muscleTestSource';
import { isDemo, linkableBefore, pctText, scheduleFor, TestWhen } from '../../lib/muscleTests';
import { useSession } from '../../state/session';
import { useTheme } from '../../theme/theme';
import { DemoNote, ScheduleRows } from './parts';
import { useMuscleTestsVersion } from './useMuscleTests';

export function WorkoutMuscleTests({ workoutId, startLocal }: { workoutId: string; startLocal: string }) {
  const { userId } = useSession();
  const { isWide } = useTheme();
  useMuscleTestsVersion();
  const [problem, setProblem] = useState(false);
  const tests = source.listForWorkout(userId, workoutId);
  const open = (when: TestWhen) => router.push({ pathname: '/muscles/test', params: { when, workoutId } });
  // Full width on iPhone, as wide as its words on the computer.
  const buttonStyle = [styles.button, isWide && styles.hug];
  const header = <SectionHeader title="Muscle tests" note="Muscle test" />;

  if (!tests.length) {
    function add() {
      const before = linkableBefore(source.listRecent(userId), startLocal)[0];
      if (!before) return setProblem(true);
      source.link(before.id, workoutId);
      open('after');
    }
    return (
      <View style={styles.section}>
        {header}
        {problem ? (
          <Notice type="info" label="No before test found" live>
            The after test compares against a before test taken in the 4 hours before this workout. Next time, do one
            from the Muscles tab before you train.
          </Notice>
        ) : (
          <>
            <Text variant="bodySmall" color="textSecondary">
              Test your quads before and after training to see how tired they got.
            </Text>
            <Button title="Add muscle tests" kind="secondary" style={buttonStyle} onPress={add} />
          </>
        )}
      </View>
    );
  }

  const s = scheduleFor(tests);
  const pct = s.after?.vs_before_pct;
  return (
    <View style={styles.section}>
      {header}
      {pct != null ? (
        <View style={styles.figure}>
          <Text variant="bodySmall" color="textSecondary">Quads fatigue</Text>
          <Text variant="scoreMetric" color="moderate">{pctText(pct)}</Text>
        </View>
      ) : null}
      <ScheduleRows schedule={s} results />
      {s.next_due ? (
        <Button title={s.next_due === 'after' ? 'Do the after test' : 'Do the next-morning test'} kind="secondary"
          style={buttonStyle} onPress={() => open(s.next_due!)} />
      ) : null}
      <Text variant="bodySmall" color="textSecondary" style={styles.note}>
        Fatigue = how much harder your quads had to work to hold the same position after your workout.
      </Text>
      <DemoNote show={isDemo(tests)} />
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 32 },
  figure: { marginBottom: 12, gap: 2 },
  button: { marginTop: 16 },
  hug: { alignSelf: 'flex-start' },
  note: { marginTop: 12 },
});
