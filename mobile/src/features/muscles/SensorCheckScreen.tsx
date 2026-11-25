/**
 * Sensor check, for testing only (open /muscles/sensor-check): the Demo | USB switch, the USB sensor's live
 * numbers, and a 10-second raw recording to download as the agreed time_us,adc CSV plus a .json info file.
 */
import { useEffect, useRef, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { Button } from '../../components/Button';
import { Chips } from '../../components/Editors';
import { ListRow } from '../../components/ListRow';
import { LiveText } from '../../components/LiveText';
import { Notice } from '../../components/Notice';
import { Page } from '../../components/Page';
import { Panel } from '../../components/Panel';
import { SectionHeader } from '../../components/SectionHeader';
import { SubPageHeader } from '../../components/SubPageHeader';
import { Text } from '../../components/Text';
import { localIso } from '../../lib/muscleTests';
import { DEVICE, PATCH_SPOT } from '../../lib/usbMuscleTestSource';
import {
  addSamples, BAUD, connectUsb, hasWebSerial, newStats, onUsbSamples, onUsbState, RawSample, signalQuality, toCsv,
  usbState, UsbState,
} from '../../lib/usbSerial';
import { useSession } from '../../state/session';
import { LiveSignal } from './parts';
import { useSourceChoice, useUsbSensor } from './useMuscleTests';

const RECORD_US = 10e6;
const STATE_TEXT: Record<UsbState, string> = {
  idle: 'Not connected', connecting: 'Connecting…', connected: 'Connected', not_found: 'No sensor found',
  unsupported: 'Browser not supported', lost: 'Disconnected',
};

type Recording = { samples: RawSample[]; at: string };

/** Saves a file through the browser's own download. Web only, like the rest of this page. */
function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function SensorCheckScreen() {
  const { userId } = useSession();
  const [choice, setChoice] = useSourceChoice();
  const { state, stats, live } = useUsbSensor();
  const [recording, setRecording] = useState(false);
  const [last, setLast] = useState<Recording | null>(null);
  const stopRec = useRef<(() => void) | null>(null);
  useEffect(() => () => stopRec.current?.(), []);
  const connected = state === 'connected';
  const web = Platform.OS === 'web';

  function record() {
    const samples: RawSample[] = [];
    const at = localIso(new Date());
    setRecording(true);
    const finish = (keep: boolean) => {
      stopSamples();
      stopState();
      stopRec.current = null;
      setRecording(false);
      if (keep) setLast({ samples, at });
    };
    const stopSamples = onUsbSamples((batch) => {
      for (const s of batch) {
        if (samples.length && s.t_us - samples[0].t_us >= RECORD_US) return finish(true);
        samples.push(s);
      }
    });
    // The cable coming out mid-recording throws the recording away, a short file would only confuse.
    const stopState = onUsbState(() => usbState() !== 'connected' && finish(false));
    stopRec.current = () => {
      stopSamples();
      stopState();
    };
  }

  function save(r: Recording) {
    const st = newStats();
    addSamples(st, r.samples);
    const seconds = (r.samples[r.samples.length - 1].t_us - r.samples[0].t_us) / 1e6;
    const info = {
      device: DEVICE, board: 'Arduino Uno', baud: BAUD, recorded_at: r.at, tester_id: userId, muscle: 'quads',
      side: 'left', patch_spot: PATCH_SPOT, seconds: Math.round(seconds * 1000) / 1000, samples: r.samples.length,
      sample_rate_hz: Math.round(((r.samples.length - 1) / seconds) * 10) / 10, gaps: st.gaps,
      clipped: st.clipped, adc_min: st.min, adc_max: st.max, malformed_lines_on_page: stats.malformed,
    };
    const name = `emg_${r.at.replace(/:/g, '-')}`;
    download(`${name}.csv`, toCsv(r.samples), 'text/csv');
    download(`${name}.json`, `${JSON.stringify(info, null, 2)}\n`, 'application/json');
  }

  return (
    <Page>
      <SubPageHeader back="Muscles" home="/muscles" label="Muscle tests" title="Sensor check"
        intro="For testing the USB sensor. Shows its raw numbers and records a short file to send back." />
      <View style={styles.column}>
        <Text variant="bodySmall" color="textSecondary">Muscle tests use</Text>
        <Chips name="Muscle tests use" value={choice}
          options={[{ value: 'demo', label: 'Demo' }, { value: 'usb', label: 'USB sensor' }]}
          onPick={(v) => setChoice(v === 'usb' ? 'usb' : 'demo')} />

        {!web || !hasWebSerial() ? (
          <View style={styles.space24}>
            <Notice type="info" label="Muscle tests need the computer">
              Connect the sensor to a computer and use Chrome or Edge.
            </Notice>
          </View>
        ) : (
          <>
            <View style={styles.space24}><LiveSignal samples={live} quality={connected ? signalQuality(stats) : '–'} /></View>
            <Panel style={styles.space16}>
              <ListRow label="Connection" value={STATE_TEXT[state]} />
              <ListRow label="Sample rate" value={connected ? `${Math.round(stats.rate_hz)} a second` : '–'} />
              <ListRow label="Gaps over 3 ms" value={String(stats.gaps)} />
              <ListRow label="ADC now" value={stats.current === null ? '–' : String(stats.current)} />
              <ListRow label="ADC min / max" value={stats.min === null ? '–' : `${stats.min} / ${stats.max}`} />
              <ListRow label="Clipped samples" value={String(stats.clipped)} />
              <ListRow label="Malformed lines" value={String(stats.malformed)} />
            </Panel>
            <Text variant="bodySmall" color="textSecondary" style={styles.space12}>
              Good: about 1000 a second, 0 gaps, nothing clipped, and the signal rises when you tighten the muscle.
            </Text>
            <View style={styles.actions}>
              {connected ? (
                <Button title="Record 10 s" busy={recording} busyTitle="Recording…" onPress={record} />
              ) : (
                <Button title="Connect" busy={state === 'connecting'} busyTitle="Connecting…" onPress={() => connectUsb(true)} />
              )}
              <Button title="Download CSV" kind="secondary" disabled={!last || recording} onPress={() => last && save(last)} />
            </View>
            {last ? (
              <View style={styles.space16}>
                <SectionHeader title="Last recording" />
                <LiveText variant="bodySmall" color="textSecondary">
                  {`${last.samples.length} samples at ${last.at.replace('T', ' ')}. Downloads a .csv and a .json.`}
                </LiveText>
              </View>
            ) : null}
          </>
        )}
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  column: { maxWidth: 560, gap: 6 },
  space12: { marginTop: 12 },
  space16: { marginTop: 16 },
  space24: { marginTop: 24 },
  actions: { marginTop: 24, gap: 12 },
});
