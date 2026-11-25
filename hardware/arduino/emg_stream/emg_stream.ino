/*
  emg_stream: sends the Muscle Sensor V3 signal to the computer over USB, 1000 samples a second.

  Every line is one sample, "micros,adc", for example "5123456,312". micros is the Arduino's clock in
  microseconds and adc is the A0 reading from 0 to 1023. The app works out the rate, gaps and clipping
  from these, so there's no filtering or baseline here. The one "#ready" line at startup is ignored by the app.

  Wiring (Arduino Uno + Advancer Technologies Muscle Sensor V3)
    Sensor SIG  -> A0
    Sensor GND  -> GND
    Sensor +Vs and -Vs go to the sensor's own batteries (two 9 V), not to the Arduino.

  Before the first test
    1. Check with a multimeter between SIG and GND that SIG stays under 5 V while you tighten the muscle as
       hard as you can. If it goes over, turn the gain knob on the sensor down and check again.
       Over 5 V can damage the Arduino's A0 pin.
    2. Keep the laptop unplugged from the wall during tests. Running on battery keeps mains noise out of the
       signal and keeps you isolated from the wall socket while the pads are on your skin.
    3. Close the Arduino IDE's Serial Monitor before using the app. Only one program can hold the port.

  Settings: board "Arduino Uno", 230400 baud (115200 is too slow for 1000 lines a second).
*/

const unsigned long BAUD = 230400;
const unsigned long PERIOD_US = 1000;  // one sample every millisecond
const int SIGNAL_PIN = A0;

unsigned long nextSample;

void setup() {
  Serial.begin(BAUD);
  Serial.print("#ready\n");
  nextSample = micros();
}

void loop() {
  // A timer instead of delay(), so the time spent reading and sending doesn't stretch the period.
  unsigned long now = micros();
  if ((long)(now - nextSample) < 0) return;
  nextSample += PERIOD_US;
  // If sending fell far behind (the computer stopped reading), start fresh instead of sending a burst.
  if ((long)(now - nextSample) > (long)(10 * PERIOD_US)) nextSample = now + PERIOD_US;

  int adc = analogRead(SIGNAL_PIN);
  Serial.print(now);
  Serial.print(',');
  Serial.print(adc);
  Serial.print('\n');
}
