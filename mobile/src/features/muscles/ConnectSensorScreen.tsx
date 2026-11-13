/**
 * "Connect the sensor": the USB stand-in for Patch setup step 1 (Bluetooth pairing) on the computer. Plug in the
 * Arduino, press Connect, pick its port once, then the live signal shows with Good or Poor like step 3.
 * Not in Figma yet, built from the Layer 2 USB brief.
 */
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '../../components/Button';
import { ListRow } from '../../components/ListRow';
import { Notice } from '../../components/Notice';
import { NumberedSteps } from '../../components/NumberedSteps';
import { Page } from '../../components/Page';
import { Panel } from '../../components/Panel';
import { StepBar } from '../../components/SetupFrame';
import { Text } from '../../components/Text';
import { connectUsb, hasWebSerial, signalQuality } from '../../lib/usbSerial';
import { LiveSignal } from './parts';
import { useUsbSensor } from './useMuscleTests';

const STEPS = [
  'Plug the Arduino into this computer with its USB cable.',
  'Check the sensor is on its own batteries.',
  'Unplug the laptop from the wall while you test.',
];

const PROBLEM: Partial<Record<string, { label: string; text: string }>> = {
  unsupported: { label: 'Browser not supported', text: 'Use Chrome or Edge on a computer.' },
  not_found: { label: 'No sensor found', text: 'Check the USB cable and that the Arduino sketch is uploaded.' },
  lost: { label: 'Sensor disconnected', text: 'Check the cable, then try again.' },
};

export default function ConnectSensorScreen() {
  const { state, stats, live } = useUsbSensor();
  const [asked, setAsked] = useState(false);
  const supported = hasWebSerial();
  const connected = state === 'connected';
  // A port allowed on an earlier visit reconnects by itself, with no picker.
  useEffect(() => {
    if (supported) connectUsb(false);
  }, [supported]);

  const problem = !supported ? PROBLEM.unsupported : asked || state === 'lost' ? PROBLEM[state] : undefined;
  const done = () => (router.canGoBack() ? router.back() : router.replace('/muscles/setup'));

  return (
    <Page>
      <View style={styles.column}>
        <StepBar label="Patch setup · Step 1 of 3" step={1} />
        <Text variant="h1" accessibilityRole="header">Connect the sensor</Text>
        <Text variant="body" color="textSecondary" style={styles.space8}>
          The sensor sends its signal to this computer over USB.
        </Text>
        {connected ? (
          <>
            <View style={styles.space24}><LiveSignal samples={live} quality={signalQuality(stats)} /></View>
            <Text variant="bodySmall" color="textSecondary" style={styles.space12}>
              Tighten your quads and the signal should rise, then fall when you relax.
            </Text>
            <Panel style={styles.space16}>
              <ListRow label="Sensor" value="Connected by USB" />
              <ListRow label="Samples" value={`${Math.round(stats.rate_hz)} a second`} />
            </Panel>
            <View style={styles.actions}>
              <Button title="Continue" onPress={done} />
            </View>
          </>
        ) : (
          <>
            <View style={styles.space24}><NumberedSteps steps={STEPS} /></View>
            {problem ? (
              <View style={styles.space16}>
                <Notice type="warning" label={problem.label} live>{problem.text}</Notice>
              </View>
            ) : null}
            <View style={styles.actions}>
              {supported ? (
                <Button title="Connect" busy={state === 'connecting'} busyTitle="Connecting…"
                  onPress={async () => {
                    setAsked(true);
                    await connectUsb(true);
                  }} />
              ) : null}
              <Button title="Cancel" kind="text" onPress={done} />
            </View>
          </>
        )}
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  // One readable column on the computer, like the other setup steps.
  column: { maxWidth: 560 },
  space8: { marginTop: 8 },
  space12: { marginTop: 12 },
  space16: { marginTop: 16 },
  space24: { marginTop: 24 },
  actions: { marginTop: 28, gap: 12 },
});
