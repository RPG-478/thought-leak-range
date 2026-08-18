# VAGO synchronous timing probe

We tested the public VAGO benchmark instead of inferring its timing semantics only from source code.

- Upstream: `VAGOsolutions/SauerkrautLM-Doom-MultiVec`
- Commit: `b4c3fdfd47cff530f69e8808eae4cc5545671772`
- ViZDoom: 1.3.0
- Scenario: stock `defend_the_center`
- Date: 2026-08-19

## Direct wait test

The game returned by upstream `setup_game()` was `Mode.PLAYER`. After explicitly advancing 70 tics,
we waited without sending another ViZDoom command.

| Wall-clock wait | Episode-time delta | State-number delta | Screen hash | HP delta |
|---:|---:|---:|---|---:|
| 250 ms | 0 | 0 | unchanged | 0 |
| 650 ms | 0 | 0 | unchanged | 0 |
| 2,000 ms | 0 | 0 | unchanged | 0 |

The immediately following `make_action(..., 4)` advanced exactly four tics and changed the screen.

As a positive control, changing only the mode to `ASYNC_PLAYER`, starting an action, waiting 650 ms,
and then refreshing state advanced 24 tics. About 23 background tics matches `35 Hz * 0.65 s = 22.75`;
the remaining tic is the explicit refresh call. This rules out a probe that was simply unable to detect
asynchronous progression. (`get_state()` alone returns the last cached state until it is refreshed.)

## Controlled 0 ms vs 650 ms A/B

We then used upstream `run_benchmark()` with `realtime=True`, `frame_skip=4`, the same seed, and the
same fixed `turn_left+shoot` policy. Only policy delay differed. The episode timeout was shortened to
70 tics so the probe would finish quickly.

| | 0 ms policy | 650 ms policy |
|---|---:|---:|
| Wall time | 2.906 s | 12.694 s |
| Steps | 18 | 18 |
| Kills | 1 | 1 |
| Final HP | 100 | 100 |
| RGB observation hashes | identical | identical |
| Depth observation hashes | identical | identical |

All 18 observations matched bit-for-bit. The extra 9.8 seconds existed only in wall-clock time.

## Interpretation

In the published runner, both API inference and the residual `--realtime` sleep occur while the
synchronous world is stopped. Each decision advances exactly `frame_skip` game tics after the response.
The reported API latency is therefore not observation age in an evolving world, and it cannot make an
enemy move closer during inference in this implementation.

For the same reason, increasing `frame_skip` to 20 does not give a slow LLM additional in-game thinking
time: inference already has no game-time deadline. It only holds each returned action for 20 tics and
reduces observation frequency, so it does not control for a latency disadvantage in the published loop.

This does not dispute VAGO's 31 ms inference measurement or its specialized model's score. It disputes
the causal interpretation that LLM scores are low because enemies continue moving during API latency,
and it shows that the baseline is not an unpaused cloud-control architecture.

## Reproduce

```powershell
.venv\Scripts\python.exe tests\manual_vago_sync_probe.py `
  --vago-root ..\..\artifacts\vago-upstream
```

No API key or paid inference is required.
