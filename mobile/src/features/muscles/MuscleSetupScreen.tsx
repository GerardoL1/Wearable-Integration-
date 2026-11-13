/**
 * Patch setup steps 2 (where the patch goes) and 3 (check the signal). With the USB sensor, step 3 shows its live
 * signal, and "Connect the sensor" (ConnectSensorScreen) stands in for step 1 until it's connected.
 * Figma "Patch setup 2 Placement" and "3 Signal".
 */
import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '../../components/Button';
import { ListRow } from '../../components/ListRow';
import { NumberedSteps } from '../../components/NumberedSteps';
import { Page } from '../../components/Page';
import { Panel } from '../../components/Panel';
import { SectionHeader } from '../../components/SectionHeader';
import { StepBar } from '../../components/SetupFrame';
import { Text } from '../../components/Text';
import { Notice } from '../../components/Notice';
import { muscleTestSource } from '../../lib/muscleTestSource';
import { signalQuality } from '../../lib/usbSerial';
import { DemoNote, LiveSignal, usePreviewSignal } from './parts';
import { useMuscleTestsVersion, useUsbSensor } from './useMuscleTests';

const PLACE_QUADS = [
  'Clean and dry the skin on the front of your thigh.',
  'Stick it lengthwise, halfway between hip and knee, on the middle of the thigh.',
  'Press firmly for 10 seconds so both pads touch the skin.',
];
// Only the quads have placement steps and a tested hold so far, so the others wait.
const LATER = ['Hamstrings', 'Glutes', 'Chest'];

export default function MuscleSetupScreen() {
  const [step, setStep] = useState<2 | 3>(2);
  useMuscleTestsVersion();
  const usb = muscleTestSource.kind === 'device';
  const demoPreview = usePreviewSignal();
  const sensor = useUsbSensor();
  const preview = usb ? sensor.live : demoPreview;
  const back = () => (router.canGoBack() ? router.back() : router.replace('/muscles'));

  if (step === 2) {
    return (
      <Page>
        <View style={styles.column}>
        <StepBar label="Patch setup · Step 2 of 3" step={2} />
        <Text variant="h1" accessibilityRole="header">Where will it go today?</Text>
        <Text variant="body" color="textSecondary" style={styles.space8}>
          The patch measures one muscle at a time. Put it on the muscle you will train hardest.
        </Text>
        <Panel style={styles.space24}>
          <ListRow label="Quads" value="Selected" />
          {LATER.map((m) => <ListRow key={m} label={m} comingSoon onPress={() => {}} />)}
        </Panel>
        <View style={styles.space24}>
          <SectionHeader title="How to place it" />
          <NumberedSteps steps={PLACE_QUADS} />
        </View>
        <View style={styles.actions}>
          <Button title="Continue" onPress={() => setStep(3)} />
          <Button title="Cancel" kind="text" onPress={back} />
        </View>
      </View>
      </Page>
    );
  }
  return (
    <Page>
        <View style={styles.column}>
      <StepBar label="Patch setup · Step 3 of 3" step={3} />
      <Text variant="h1" accessibilityRole="header">Check the signal</Text>
      <Text variant="body" color="textSecondary" style={styles.space8}>Tighten your quads three times, then relax.</Text>
      {usb && !muscleTestSource.canRecord ? (
        <View style={styles.space16}>
          <Notice type="info" label="Muscle tests need the computer">
            Connect the sensor to a computer and use Chrome or Edge.
          </Notice>
        </View>
      ) : (
        <View style={styles.space24}>
          <LiveSignal samples={preview}
            quality={usb ? (muscleTestSource.connected ? signalQuality(sensor.stats) : 'Not connected') : 'Good'} />
        </View>
      )}
      <Text variant="bodySmall" color="textSecondary" style={styles.space12}>
        Three clear bursts and a quiet baseline: the pads are making good contact.
      </Text>
      <Panel style={styles.space16}>
        <ListRow label="Muscle" value="Quads" />
        {usb ? <ListRow label="Sensor" value={muscleTestSource.connected ? 'Connected by USB' : 'Not connected'} />
          : <ListRow label="Patch battery" value="82%" />}
      </Panel>
      <DemoNote show={muscleTestSource.kind === 'demo'} />
      <View style={styles.actions}>
        {!muscleTestSource.canRecord ? null : muscleTestSource.connected ? (
          <Button title="Start the muscle test" onPress={() => router.replace({ pathname: '/muscles/test', params: { when: 'before' } })} />
        ) : <Button title="Connect the sensor" onPress={() => router.push('/muscles/connect')} />}
        <Button title="Place it again" kind="text" onPress={() => setStep(2)} />
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
  actions: { marginTop: 28, gap: 12 },
});
