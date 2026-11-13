# Open decisions

Team decisions the code is waiting on. Until each is made, the code uses a clearly marked placeholder
(`"placeholder": true` in the API). Settled ones move to the "Decided" list in `ml_llm_plan.md`.

## Readiness score

| Decision | Placeholder today | Where it lives |
|---|---|---|
| What a "normal" night should score | 50, with 10 points per standard deviation from your usual | `server/app/readiness/scoring.py` |
| Low / Moderate / Ready cut-offs | Low below 40, Ready from 70 | `server/app/readiness/scoring.py` |
| Minimum data before a score is shown | At least 7 usable nights in the baseline (`BASELINE_MIN_NIGHTS`), and at least one z-score that night | `preprocessing/layer1/config.py`, `scoring.py` |
| Weight of sleep against HRV and resting HR | All five inputs (HRV, resting HR, sleep time, efficiency, fragmentation) count equally | `scoring.py` |
| Whether a short night should force Low | A night under 3 hours gets no score (status `short_sleep`), and is kept out of the baselines | `scoring.py`, `preprocessing/layer1/quality.py` |
| How much sweat data (Layer 3) can move the score | Not used yet. Proposed cap: ±5 points | Future readiness model |
| "Your usual" range | Baseline mean ± 1 standard deviation | `server/app/readiness/usual.py` |
| Do measures inside the usual range move the score? | Yes, every measure moves it a little, even inside the usual range. The Figma "Why this score" screen says they don't ("Measures within your usual range don't move it"), so either that sentence or the formula has to change | `scoring.py`, Figma Round 6 |

The trained readiness model will replace the first, fourth and sixth rows. The team still has to agree what
the model may and may not do (for example the cut-offs and the Layer 3 cap) before it ships.

## Readiness model inputs to define

`server/app/readiness/features.py` is where these go, but each needs a definition from the team before it's built.

| Input | Questions |
|---|---|
| HRV trend (7 nights vs 28) | Average the log HRV or the raw ms? Compare as a difference in standard deviations, or a percentage? How many of the 7 nights must have HRV? |
| Sleep debt (last 3 and 7 nights) | Debt against what: the person's usual sleep (baseline mean), a fixed need like 8 hours, or one based on age? Does a missing night count as zero sleep or get skipped? Does sleeping more than usual pay debt back? |
| Poor nights in a row | What makes a night poor: total sleep below the usual range, efficiency below it, a Low score, or any of these? Does a missing night break the run? |
| Bedtime and wake time vs usual | Usual means the baseline average of the onset and wake clock times? Measured in minutes earlier or later? |
| Hard training day | Effort of at least some level (7?), a load over some amount, or the person's own heavy days? |
| Training load balance | Use the last 7 days against the last 28 (acute to chronic), and if so as a ratio or a difference? |

## Muscle recovery (Layer 2)

The app shows these with placeholders today. Fatigue is how much harder the muscle works to hold the same wall sit
than in the before test, as a %.

| Decision | Placeholder today | Where it lives |
|---|---|---|
| Fatigued / recovering / ready cut-offs | Fatigued from +15%, recovering from +5%, ready below +5% | `mobile/src/lib/muscleTests.ts` (`FATIGUED_FROM_PCT`, `RECOVERING_FROM_PCT`) |
| Which test sets today's state | The next-morning test if there is one, else the after test | `muscleTests.ts` (`recoveryOf`) |
| When a muscle is ready again | 2 hours per % after that test (+21% is about 42 h), ready once that time has passed | `muscleTests.ts` (`READY_HOURS_PER_PCT`) |
| Muscles that weren't tested | Shown as "Not tested". Estimating them from logged exercises needs exercises and sets, and an exercise-to-muscle table | Not built |
| Linking a before test to its workout | A before test from the 4 hours before the workout started | `muscleTests.ts` (`LINK_WINDOW_HOURS`) |
| Next-morning test after re-sticking the patch | Compared with the before test as it is, though moving the patch changes the signal. Options: a fresh reference each morning, or a reference hold at the end of the after session | Not decided |
| Tests with different gain settings | Not checked yet. They shouldn't be compared, since a different gain changes every % | Not decided |
| "Within 5 minutes of the last set" for the after test | Asked for in the wording, not enforced | Not decided |
| What makes a signal too weak to use | No 20 s hold found, under 900 samples a second, over 1% gaps, over 1% clipping, or a hold under 30 ADC counts above rest | `server/app/services/muscle_tests.py` (`MIN_RISE_ADC` and the rules in `process`) |
| Finding the hold | Half-second averages, above halfway from the resting level to the 90th percentile after the rest, the longest such stretch, at least 20 s | `muscle_tests.py` (`process`) |
| Units of env_mean | ADC counts above the resting median (0 to 1023 range), from the sensor's own envelope output. Only the % between tests is shown | `muscle_tests.py` |

## Later

- Illness signals (respiratory rate, wrist temperature): when to start collecting them, and how the warning
  banner should read.
- Wording rules for the LLM explanation, beyond "only cite inputs whose Last night row isn't Usual".
