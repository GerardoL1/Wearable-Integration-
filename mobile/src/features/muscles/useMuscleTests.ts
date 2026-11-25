import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState, useSyncExternalStore } from 'react';

import { LiveSample } from '../../lib/muscleTests';
import {
  muscleTestSource, setSourceChoice, sourceChoice, SourceChoice, subscribeTests, testsVersion,
} from '../../lib/muscleTestSource';
import { usbServer } from '../../lib/usbMuscleTestSource';
import { ADC_MAX, onUsbSamples, onUsbState, RawSample, SignalStats, usbState, UsbState, usbStats } from '../../lib/usbSerial';
import { useSession } from '../../state/session';

const CHOICE_KEY = 'layer2.muscleSource';
let choiceLoaded = false;

/**
 * Re-renders the screen whenever a muscle test is saved or linked, or the source is switched. With the USB source
 * it also fetches the tester's tests from the server, so results recorded on the computer show on the iPhone.
 */
export function useMuscleTestsVersion() {
  const { serverUrl, userId } = useSession();
  const version = useSyncExternalStore(subscribeTests, testsVersion);
  const choice = sourceChoice();
  useEffect(() => {
    if (choiceLoaded) return;
    choiceLoaded = true;
    AsyncStorage.getItem(CHOICE_KEY).then((c) => c === 'usb' && setSourceChoice('usb')).catch(() => {});
  }, []);
  useEffect(() => {
    usbServer.url = serverUrl;
    // A failed fetch leaves the last list showing. The screens work the same either way.
    if (choice === 'usb') muscleTestSource.refresh(userId).catch(() => {});
  }, [choice, userId, serverUrl]);
  return version;
}

/** The Demo | USB switch, remembered on this device. */
export function useSourceChoice(): [SourceChoice, (c: SourceChoice) => void] {
  useMuscleTestsVersion();
  return [sourceChoice(), (c) => {
    setSourceChoice(c);
    AsyncStorage.setItem(CHOICE_KEY, c).catch(() => {});
  }];
}

const SHOWN = 150;

/** The USB sensor's connection, its stats a few times a second, and the live signal at about 50 points a second. */
export function useUsbSensor(): { state: UsbState; stats: SignalStats; live: LiveSample[] } {
  const state = useSyncExternalStore(onUsbState, usbState);
  const [stats, setStats] = useState(usbStats);
  const [live, setLive] = useState<LiveSample[]>([]);
  useEffect(() => {
    let pending: LiveSample[] = [];
    let nextDraw = 0;
    const stop = onUsbSamples((batch: RawSample[]) => {
      for (const s of batch) {
        // A clock far behind means the Arduino restarted, so drawing starts over.
        if (s.t_us < nextDraw && nextDraw - s.t_us < 1e6) continue;
        nextDraw = s.t_us + 20_000;
        pending.push({ t_ms: s.t_us / 1000, level: s.adc / ADC_MAX });
      }
    });
    // Drawn in steps, since a re-render for every sample would be 1000 a second.
    const timer = setInterval(() => {
      setStats(usbStats());
      if (!pending.length) return;
      const add = pending;
      pending = [];
      setLive((prev) => [...prev, ...add].slice(-SHOWN));
    }, 100);
    return () => {
      stop();
      clearInterval(timer);
    };
  }, []);
  return { state, stats, live };
}
