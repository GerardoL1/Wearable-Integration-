import { useSyncExternalStore } from 'react';

import { subscribeTests, testsVersion } from '../../lib/muscleTestSource';

/** Re-renders the screen whenever a muscle test is saved or linked. */
export const useMuscleTestsVersion = () => useSyncExternalStore(subscribeTests, testsVersion);
