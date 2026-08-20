# V4 clock repair: ten paired runs

The first clock ablation used `Mode.PLAYER` plus a Python asyncio loop for the
unpaused condition. A long native/provider stall could therefore stop the
Python loop and the supposedly moving world together. The unpaused condition
now uses ViZDoom `ASYNC_PLAYER`; the VAGO-style condition remains `PLAYER`.

## Conditions

- `defend_the_center`, skill 1, 15 simulation seconds
- seeds 7 through 16, one paired run per seed
- `meta-llama/llama-3.1-8b-instruct` through Groq, no fallback
- V4 `direct-motor`, 400 ms motor-token TTL, three configured lanes
- all 20 startup probes passed; API errors: 0
- odd seeds ran unpaused first; even seeds ran stopped first

## Results

| Metric | `unpaused` / `ASYNC_PLAYER` | `vago-sync` / `PLAYER` |
|---|---:|---:|
| KILLCOUNT total / mean | 25 / 2.5 | **64 / 6.4** |
| HITCOUNT total | 25 | **64** |
| game ticks total / mean | 4,536 / 453.6 | 4,662 / 466.2 |
| runs reaching 15 seconds | 0 / 10 | 2 / 10 |
| requests launched / completed | 924 / 902 | 1,492 / 1,492 |
| request errors | 0 | 0 |
| accepted-token semantic accuracy | 94.6% | 90.3% |
| accepted latency p50 / p95 | 265 / 328 ms | 218 / 282 ms |
| motor preemptions | 642 | **0** |
| coalesced observations | 72 | **0** |
| reported cost | $0.00962875 | $0.01549222 |

The stopped condition won every pair: 10/10, with a mean stopped-minus-unpaused
kill difference of +3.9 (range +2 to +6). The two-sided paired sign-test value
is 0.001953125. Total reported cost was $0.02512097.

## Interpretation

The stopped condition did not make the model more accurate; its semantic
accuracy was lower. It removed the time during which an old decision could be
preempted by a newer observation and the player could be damaged while waiting.
This is a clock ablation, not evidence that this structured-label turret beats
VAGO's specialized model or that the two systems have identical action spaces.

The amusing side effect survived the repair: the unpaused run selected FIRE 60
times but only 3 ammo decrements were observed; the stopped run selected FIRE
638 times and observed 82 decrements. Thought time can be made free; weapon
cooldown remains stubbornly employed.

The Japanese project record, including raw artifact paths, is
[here](../../../docs/実験/2026-08-20-V4時計修正版10回比較.md).
