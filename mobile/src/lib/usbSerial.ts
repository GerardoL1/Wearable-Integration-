/**
 * The muscle sensor over USB: an Arduino Uno running hardware/arduino/emg_stream sends "micros,adc" lines at
 * 230400 baud, and the browser reads them with Web Serial (Chrome and Edge on a computer only).
 * The line parsing and the signal stats are plain functions with no imports, so scripts/check-convert.js tests them.
 */

export const BAUD = 230400;
export const ADC_MAX = 1023;
export const CLIP_ADC = 1020;
export const GAP_US = 3000;
export const GOOD_RATE_HZ = 900;

/** One reading. t_us keeps counting past the Arduino's micros() rolling over at 2^32 (about every 71 minutes). */
export type RawSample = { t_us: number; adc: number };

export type LineParser = { rest: string; lastRaw: number | null; wraps: number; malformed: number };
export const newParser = (): LineParser => ({ rest: '', lastRaw: null, wraps: 0, malformed: 0 });

const LINE = /^(\d{1,10}),(\d{1,4})$/;
const WRAP = 2 ** 32;
const MAX_LINE = 64; // a real line is at most 16 characters

/**
 * Turns the next chunk from the port into samples. Lines can arrive split over chunks, so the unfinished end
 * waits for the next one. Lines starting with "#" are notes from the sketch. ready is true when "#ready" came,
 * which happens each time the Arduino restarts (opening the port restarts it).
 */
export function feed(p: LineParser, chunk: string): { samples: RawSample[]; ready: boolean } {
  const lines = (p.rest + chunk).split('\n');
  p.rest = lines.pop() ?? '';
  if (p.rest.length > MAX_LINE) {
    p.rest = '';
    p.malformed += 1;
  }
  const samples: RawSample[] = [];
  let ready = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('#')) {
      if (line === '#ready') {
        ready = true;
        p.lastRaw = null;
        p.wraps = 0;
      }
      continue;
    }
    const m = LINE.exec(line);
    const micros = m ? Number(m[1]) : NaN;
    const adc = m ? Number(m[2]) : NaN;
    if (!m || micros >= WRAP || adc > ADC_MAX) {
      p.malformed += 1;
      continue;
    }
    if (p.lastRaw !== null && micros <= p.lastRaw) {
      // A big jump back is micros() rolling over. A small one is a garbled line.
      if (p.lastRaw - micros > WRAP / 2) p.wraps += 1;
      else {
        p.malformed += 1;
        continue;
      }
    }
    p.lastRaw = micros;
    samples.push({ t_us: micros + p.wraps * WRAP, adc });
  }
  return { samples, ready };
}

/** What the sensor check page shows. rate_hz is over the last second of samples. */
export type SignalStats = {
  count: number; rate_hz: number; gaps: number; min: number | null; max: number | null; current: number | null;
  clipped: number; malformed: number;
};

export type StatsState = SignalStats & { recent: number[]; last_t: number | null };

export const newStats = (): StatsState => ({
  count: 0, rate_hz: 0, gaps: 0, min: null, max: null, current: null, clipped: 0, malformed: 0, recent: [], last_t: null,
});

export function addSamples(st: StatsState, samples: RawSample[]): void {
  for (const s of samples) {
    if (st.last_t !== null && s.t_us - st.last_t > GAP_US) st.gaps += 1;
    st.last_t = s.t_us;
    st.count += 1;
    st.current = s.adc;
    st.min = st.min === null ? s.adc : Math.min(st.min, s.adc);
    st.max = st.max === null ? s.adc : Math.max(st.max, s.adc);
    if (s.adc >= CLIP_ADC) st.clipped += 1;
    st.recent.push(s.t_us);
  }
  const newest = st.recent[st.recent.length - 1];
  let drop = 0;
  while (drop < st.recent.length && newest - st.recent[drop] > 1e6) drop += 1;
  if (drop) st.recent.splice(0, drop);
  const span = (st.recent[st.recent.length - 1] - st.recent[0]) / 1e6;
  st.rate_hz = st.recent.length > 1 && span > 0 ? (st.recent.length - 1) / span : 0;
}

/** Good when the rate is right and nothing is clipping. Shown next to the live signal. */
export const signalQuality = (st: SignalStats): 'Good' | 'Poor' =>
  st.rate_hz >= GOOD_RATE_HZ && (st.count === 0 || st.clipped / st.count <= 0.01) ? 'Good' : 'Poor';

/** The agreed raw file: a time_us,adc header, then one line per sample. */
export const toCsv = (samples: RawSample[]) => `time_us,adc\n${samples.map((s) => `${s.t_us},${s.adc}`).join('\n')}\n`;

// ---------------------------------------------------------------- the connection, web only

// Web Serial isn't in TypeScript's own DOM types, so this is the small part of it used here.
type SerialPortLike = {
  open(o: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readable: ReadableStream<Uint8Array> | null;
};
type SerialLike = {
  getPorts(): Promise<SerialPortLike[]>;
  requestPort(): Promise<SerialPortLike>;
  addEventListener(type: 'disconnect', l: (e: { target: unknown }) => void): void;
};
const serial = (): SerialLike | null =>
  (typeof navigator !== 'undefined' && (navigator as unknown as { serial?: SerialLike }).serial) || null;

/** Chrome and Edge on a computer. Not Safari, Firefox or the iPhone app. */
export const hasWebSerial = () => serial() !== null;

export type UsbState = 'idle' | 'connecting' | 'connected' | 'not_found' | 'unsupported' | 'lost';

let port: SerialPortLike | null = null;
let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
let state: UsbState = 'idle';
let parser = newParser();
let stats = newStats();
const sampleListeners = new Set<(s: RawSample[]) => void>();
const stateListeners = new Set<() => void>();

function setState(s: UsbState) {
  state = s;
  stateListeners.forEach((l) => l());
}

export const usbState = () => state;
export const usbStats = (): SignalStats => ({ ...stats, malformed: parser.malformed });

export function resetUsbStats() {
  stats = newStats();
  parser.malformed = 0;
}

export function onUsbState(l: () => void): () => void {
  stateListeners.add(l);
  return () => {
    stateListeners.delete(l);
  };
}

export function onUsbSamples(l: (s: RawSample[]) => void): () => void {
  sampleListeners.add(l);
  return () => {
    sampleListeners.delete(l);
  };
}

let watching = false;

/**
 * Opens the sensor. ask shows the browser's port picker when no port was allowed before, which only works
 * straight from a tap. Later visits reconnect to the allowed port without the picker.
 */
export async function connectUsb(ask: boolean): Promise<UsbState> {
  const s = serial();
  if (!s) {
    setState('unsupported');
    return state;
  }
  if (state === 'connected' || state === 'connecting') return state;
  if (!watching) {
    watching = true;
    s.addEventListener('disconnect', (e) => {
      if (e.target === port) lose();
    });
  }
  setState('connecting');
  try {
    let p: SerialPortLike | null = (await s.getPorts())[0] ?? null;
    if (!p && ask) p = await s.requestPort().catch(() => null); // closing the picker without a choice lands here
    if (!p) {
      setState('not_found');
      return state;
    }
    await p.open({ baudRate: BAUD });
    port = p;
    parser = newParser();
    stats = newStats();
    setState('connected');
    read(p);
  } catch {
    // Most often the port is busy, like the Arduino IDE's Serial Monitor still holding it.
    setState('not_found');
  }
  return state;
}

function lose() {
  reader?.cancel().catch(() => {});
  port?.close().catch(() => {});
  reader = null;
  port = null;
  if (state === 'connected') setState('lost');
}

async function read(p: SerialPortLike) {
  const decoder = new TextDecoder();
  try {
    reader = p.readable?.getReader() ?? null;
    while (reader) {
      const { value, done } = await reader.read();
      if (done) break;
      const { samples, ready } = feed(parser, decoder.decode(value, { stream: true }));
      if (ready) stats = newStats(); // the bootloader's startup noise shouldn't count against the sensor
      if (samples.length) {
        addSamples(stats, samples);
        sampleListeners.forEach((l) => l(samples));
      }
    }
  } catch {
    // The cable came out, or the reader was cancelled.
  }
  if (port === p) lose();
}
