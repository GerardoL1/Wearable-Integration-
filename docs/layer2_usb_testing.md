# Testing the muscle sensor over USB (Windows)

The Arduino Uno reads the Muscle Sensor V3 and sends its signal to the computer over USB. The app reads it in
Chrome or Edge (Web Serial), uploads each test to the server, and the server works out the result.

You need: the Arduino Uno and its USB cable, the Muscle Sensor V3 with its two 9 V batteries, electrode pads,
a multimeter, and Chrome or Edge.

> **Before the first test:** the server's `main.py` has to include the muscle test endpoints. That file belongs
> to the Layer 1 tab. Until it's added, uploads get "Not Found". The sensor check page (step 4) works without it.

## 1. Upload the sketch

1. Install the Arduino IDE from arduino.cc if you don't have it.
2. Open `hardware\arduino\emg_stream\emg_stream.ino`.
3. **Tools > Board**: Arduino Uno. **Tools > Port**: the COM port that appears when you plug the Arduino in.
4. Click **Upload** (the arrow). Wait for "Done uploading".
5. If you opened the Serial Monitor to look, **close it**. Only one program can use the port at a time.

Wiring: sensor **SIG to A0**, sensor **GND to GND**. The sensor's +Vs and -Vs go to its own batteries.

## 2. Safety checks

1. With the pads on your thigh, put the multimeter (DC volts) between **SIG** and **GND**. Tighten your quads as
   hard as you can. It must stay **under 5 V**. If it goes over, turn the sensor's gain knob down and check again.
2. **Unplug the laptop from the wall.** Run it on battery for every test.

## 3. Start the server and the app

Command Prompt window 1, the server:

```bash
cd C:\Users\gerar\Downloads\recovery-platform_layer2-usb\server
C:\Users\gerar\Downloads\recovery-platform_2026-10-08\server\.venv\Scripts\activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

Command Prompt window 2, the app:

```bash
cd C:\Users\gerar\Downloads\recovery-platform_layer2-usb\mobile
npx expo start --web
```

Open `http://localhost:8081` in **Chrome**. In **Test build**, keep the server address `http://localhost:8000`, type a
tester name (for example `tester1`) and click **Use this tester**.

## 4. Sensor check

1. Open `http://localhost:8081/muscles/sensor-check`.
2. Under **Muscle tests use**, pick **USB sensor**.
3. Click **Connect**, pick the Arduino's port (often "USB Serial Device (COMx)" or "Arduino Uno"), click
   **Connect** in the browser's box.
4. Good numbers look like this:
   - **Sample rate** about **1000 a second**
   - **Gaps over 3 ms**: 0, or a few right after connecting
   - **Clipped samples**: 0
   - **Malformed lines**: 0, or 1 or 2 right after connecting
   - The trace stays low when you're relaxed and **rises when you tighten** your quads
5. Click **Record 10 s**. Relax for 3 seconds, tighten for 4, relax again.
6. Click **Download CSV**. Two files land in Downloads: `emg_….csv` (time_us,adc) and `emg_….json` (the info).
   These are your own recordings, so keep them out of the project folder.

## 5. A full test

1. **Muscles** tab > **Start a muscle test**. Follow the placement step.
2. On **Check the signal**, if it says **Connect the sensor**, connect it. Tighten three times and watch the signal.
3. **Start the muscle test**: rest for 5 seconds, then hold the wall sit for 30 seconds.
4. You should see **Before test saved**. Click **Start a workout**, pick **Leg day**, **Go train**.
5. **Train > Log a workout**: the name and date are filled in. Add a start time after the before test, a length,
   check your before test is picked under **Muscle test before this workout**, and **Save workout**.
6. On the workout summary, under **Muscle tests**, click **Do the after test** and do the same hold.
7. The result shows the % change. Back on the workout summary, the Muscle tests section shows the same %, and the
   **Muscles** tab shows your quads' state.

A % right after a light workout can be small or even negative. That's fine for a first test.

## 6. Quick failure tests

| Do this | You should see |
|---|---|
| Pull the USB cable out in the middle of the hold | **Sensor disconnected**, "Check the cable, then try the test again." Nothing saved. |
| Stay relaxed the whole hold | **Signal was weak** with the reason. Not saved as a result. |
| Open `http://localhost:8081/muscles/connect` in Safari or Firefox | **Browser not supported**, "Use Chrome or Edge on a computer." |
| Leave the Serial Monitor open, then click Connect | **No sensor found** |

## 7. If something fails, send back

| What | Where to find it |
|---|---|
| A screenshot of the screen | The app in Chrome |
| The numbers on the sensor check page | Sample rate, gaps, ADC min / max, clipped, malformed |
| The downloaded `.csv` and `.json` | Your Downloads folder (step 4) |
| What you did just before | A sentence is enough |
| The server window's last lines, if a test didn't save | Command Prompt window 1 |
