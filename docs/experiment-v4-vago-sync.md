# V4-S: V4 inside a VAGO-style stopped world

## Question

What happens if the same V4 motor policy is transplanted from an unpaused 35 Hz world into the
synchronous clock used by VAGO's public benchmark?

This experiment keeps V4's structured label-derived observation, six-token prompt, model, parser,
400 ms TTL, and fixed 1/2/5-tic pulses. It changes only the world-clock architecture. It is therefore a
clock ablation, **not** an ASCII+depth head-to-head against VAGO's specialized model.

## `vago-sync` semantics

```text
capture observation
  -> freeze ViZDoom while one Cloud request runs
    -> first accepted digit unfreezes exactly its fixed pulse
      -> freeze again until the response is closed
        -> capture the next observation
```

No new observation exists while the world is frozen, so configured three-lane V4 necessarily becomes
one effective serial lane. We still act on the first valid streamed digit rather than waiting for prose.
The 400 ms TTL remains enabled; a rejected or invalid response advances one fail-closed WAIT tic.

Every `sync_world_wait_finished` event records game ticks before and after the request. In the live run,
all 158 waits had `game_tick_delta=0`.

## Fresh seed-12 pair

Both runs used the current code, `meta-llama/llama-3.1-8b-instruct`, OpenRouter/Groq without fallback,
temperature 0, the same startup six-token probe, `defend_the_center`, skill 1, seed 12, and a requested
15 seconds. They were executed minutes apart on 2026-08-19.

| Metric | V4 unpaused | V4-S stopped |
|---|---:|---:|
| World during Cloud request | advances at 35 Hz | **0 game tics** |
| Effective lanes | 3 | 1 |
| Game time before death | 11.600 s | **13.886 s** |
| Wall time | 11.609 s | 47.015 s |
| KILLCOUNT / HITCOUNT | 2 / 2 | **6 / 6** |
| DAMAGECOUNT | 15 | **50** |
| Requests launched / completed | 88 / 86 | 158 / 158 |
| Accepted motor tokens | 82 | 155 |
| Token latency, all p50 / p95 | 250 / 390 ms | **219 / 328 ms** |
| TTL-expired tokens | 4 | 3 |
| WAIT game tics | 106 | **3** |
| Pulse preemptions | 38 | **0** |
| FIRE motor tics | 2 | 64 |
| Semantic errors | 5 / 86 | 24 / 158 |
| Reported API cost, including probe | $0.00091882 | $0.00163714 |

Both agents died before the requested 15 seconds. The stopped agent lasted 486 tics and the unpaused
agent 406 tics. This is one paired seed, not a population estimate.

![V4-S stopped-world replay, seed 12, six kills](https://github.com/RPG-478/latency-kills/releases/download/replays-highlights-2026-08-21/v4-vago-sync-seed12-6-kills.gif)

## The weird part: thinking is free, weapon cooldown is not

The stopped agent emitted 64 FIRE motor tics, but ammo fell only from 50 to 43. ViZDoom's shotgun still
needs game tics to become ready again; 200 ms of Cloud waiting advances no cooldown. V4-S therefore
repeatedly paid for another Cloud decision merely to advance one FIRE tic. Seven physical shots produced
six hits and six kills.

This is the exact asymmetry created by the paused clock:

- cognitive wall time is free in game time;
- bodily animation, enemy movement, and weapon cooldown still cost game tics.

The model was not silently corrected. All 24 semantic mistakes were scored and executed: **23 of
24** were `FIRE` where the local scoring rule expected `RIGHT_SHORT`; the remaining error was
`RIGHT_SHORT` instead of `RIGHT_LONG`. The accepted mistakes entered the body unchanged.

## Interpretation

The stopped clock improved this seed from two to six kills, primarily by removing latency-created idle
body time: WAIT fell from 106 tics to three and in-flight pulse preemption fell from 38 to zero. It did
not make the model accurate or immortal. It converted Cloud latency into unlimited free deliberation and
greatly increased decisions per game tic.

The paired runs also had different network latency distributions (p50 250 vs 219 ms), so the exact
threefold score ratio cannot be attributed to pausing alone. However, no amount of network jitter changes
the observed architectural fact: in `vago-sync`, all 158 request waits consumed zero game tics.

## 2026-08-21 replay insight: the stopped world also freezes aiming error

The live-world failure replay revealed that V4 frequently chose the correct direction for its captured
`x`, but the target crossed the center before the token arrived. Repeated LONG tokens then overshot the
target and erased the next firing opportunity. That failure mode cannot occur during a `vago-sync`
request: the target, crosshair, weapon state, and chosen `x` all remain frozen until the digit arrives.

This explains the stopped run's apparently extraordinary aim more directly than WAIT count alone. Its
64 FIRE motor tics became only seven physical shots because of cooldown, yet six of those seven shots hit
and produced six kills. The clock did not improve the model's spatial reasoning; it made the observed
geometry stay true until execution.

Important correction: the historical stopped run above did **not** recognize or kill the Freedoom
`MarineChainsawVzd` actor. Its six kills came only from enemies that passed the old name filter. The
worktree was then updated to recognize `MarineChainsawVzd` by name and Monster category. At the time of
this historical pair it had not yet been remeasured. The later 18-episode follow-up did perform that
measurement: 215 total kills, 11.94 average, and at least 146 kills attributed to FIRE against the Marine.
It also exposed premature FIRE and a 39.7% physical-shot hit rate against that actor. See the
[Marine recognition repair baseline](replays/2026-08-21-v4-s-marine-fixed-before-overshoot/README.md).
Those numbers still describe a paused-world controller, not aiming performance in a continuously moving
35 Hz world.

## Proposed role: V4-S as the controller oracle

The stopped condition is useful as more than a VAGO comparison. It can be the first stage of the project's
test ladder: establish whether the **System + LLM** mapping is coherent before adding real-time delay.

```text
Stage 1: V4-S stopped world
  Does one observation produce a sensible complete command?
  Can the policy aim, fire, handle every monster class, and finish cooldowns?

Stage 2: same policy in unpaused Formal D
  How much performance is lost only because observations age while the world moves?

Stage 3: asynchronous fixes
  Reduce stale-side execution, overshoot, lane interference, and missed fire windows.
```

V4-S should therefore be the correctness baseline, not the real-time headline. If it cannot kill a monster
in the frozen condition, latency is exonerated and the defect is in perception, prompt semantics, action
mapping, or game mechanics. If it succeeds while Formal D fails, the delta belongs to temporal control.
This ordering prevents every failure from being vaguely blamed on "the Cloud being slow."

## Reproduce

Stopped clock:

```powershell
uv run python -m thought_leak_range live `
  --env-file C:\path\outside\repo\.env `
  --model meta-llama/llama-3.1-8b-instruct `
  --provider Groq --no-provider-fallback `
  --tap-mode direct-motor --world-clock vago-sync --lanes 3 `
  --scenario defend_the_center --duration 15 --seed 12 `
  --motor-token-max-age-ms 400 `
  --max-tokens 16 --max-requests 200 --max-usd 0.025
```

Change only `--world-clock vago-sync` to `--world-clock unpaused` and add
`--observation-interval 0.10` for the live-world control.

Raw local artifacts:

- stopped: `runs/20260819-072938-011d2021/`
- unpaused control: `runs/20260819-073205-6d1e1eea/`
