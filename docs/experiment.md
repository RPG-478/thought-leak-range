# Experiment log

Experiment date: 2026-08-18

## What this repository tests

Can a general-purpose cloud LLM affect an FPS before its observation becomes stale?

The game is offline ViZDoom. It keeps advancing at 35 Hz while HTTP requests are in flight.
The runtime never emits native keyboard or mouse input and is deliberately not connected to
commercial games.

Three different questions were tested. They should not be merged into one claim:

1. Can streamed raw reasoning become an early motor event?
2. Can a slow LLM authorize a fast local controller for a short time?
3. Can a cloud LLM itself choose every individual trigger pull quickly enough to score kills?

## Raw reasoning版

The original design watched OpenRouter's streamed `reasoning_details` and accepted only a
request-bound action marker before the final answer. DeepSeek V4 Flash 0731 did reason about the
correct action, but commonly placed the complete marker in visible output rather than raw reasoning.
The strict parser failed closed, as intended.

An intentionally unsafe offline-only parser could react to a narrow natural-language commit such as
`So action is FIRE.`. This proved that raw thinking could be used as an event source, but also exposed
the obvious prefix problem: quoted, hypothetical, or negated language can contain action words.

The fixed-target run produced a real shot, but its mean observation-to-commit latency was 1.647 s.
This mode is retained as an experiment, not presented as the fast successful player.

## Fire-gate版

`fire-gate` changed the LLM output from a motor command to a short-lived permission:

```text
raw reasoning ARMED
  -> observation-bound lease
    -> local 35 Hz tracker may FIRE while centered
```

DeepSeek V4 Flash 0731 authorized a local controller that killed four moving Demons in 15 seconds.
The fastest valid authorization was 625 ms and the mean was 1.068 s.

This was a successful slow-brain/fast-body architecture, but it was not the LLM pulling each trigger.
The local controller owned target tracking, centering, and the exact firing tick.

## Direct-bit版

`direct-bit` was introduced to answer the stricter question. It deliberately stops being a raw-thought
experiment.

Each HTTP response is already bound to one observation by its callback. Reasoning, nonce text, and
action templates are removed. The first non-whitespace visible character is interpreted once:

```text
1 -> one FIRE tick
0 -> WAIT
anything else -> invalid and fail-closed WAIT
```

The parser never searches later prose for a convenient `1`. A returned decision is accepted only if
it belongs to the latest observation and is at most 300 ms old. A decision can still expire between
arrival and the next 35 Hz game tick.

### Sensor representation

The model receives three structured values:

```text
v=<target visible 0/1> x=<signed horizontal thousandths> a=<ammo>
```

The rule is `FIRE iff v=1, a>0, and -80<=x<=80`. Signed integer thousandths replaced decimal values
because Llama 3.1 8B made boundary mistakes around `0.080` and `0.081`. Outside magnitudes are rounded
outward so preprocessing cannot accidentally turn an outside target into an inside one.

The model still performs the boundary decision. Preprocessing does not compute the FIRE bit.

### Synthetic boundary test

Llama 3.1 8B Instruct was routed to Groq only, with provider fallback disabled and reasoning off.
Nine cases were tested twice: centered, left, right, both `±80/±81` boundaries, no target, and no ammo.

| Metric | Result |
|---|---:|
| Correct | 18 / 18 |
| Fastest | 187 ms |
| Median | 234.5 ms |
| Mean | 256.9 ms |
| Under 300 ms | 15 / 18 |
| Under 200 ms | 1 / 18 |

Stable 200 ms was not achieved. The practical design is a 300 ms freshness window that discards the
slow tail.

### Unpaused 15-second challenge

Success criterion: at least four kills in one 15-second run.

Configuration:

- Model: `meta-llama/llama-3.1-8b-instruct`
- Provider: Groq only, no fallback
- Scenario: `defend_the_center`
- World: unpaused, 35 Hz
- Local body: LEFT/RIGHT tracking only; it cannot return FIRE
- LLM: one FIRE/WAIT decision per observation
- Freshness: latest observation and at most 300 ms

Result:

| Metric | Result |
|---|---:|
| Startup FIRE probe | 219 ms, correct |
| Requests completed / errors | 27 / 0 |
| Accepted decisions | 16 |
| FIRE / WAIT | 9 / 7 |
| Semantically correct | 16 / 16 |
| Accepted decision latency | fastest 204 ms / median 265 ms / mean 255.9 ms |
| Executed FIRE ticks | 6 |
| Observation to FIRE tick | mean 273.7 ms |
| Actual shells / hits / kills | 5 / 5 / 5 |
| Ammo | 52 -> 47 |
| Damage | 65 |
| Reported API cost | `$0.00012228` |

Three accepted FIRE decisions arrived near 281 ms and expired before the next tick. They were not
rescued. Of six FIRE ticks, one occurred during weapon cooldown; five shells actually left the gun.

The player killed the fourth enemy about 8.36 seconds after arena initialization and the fifth about
10.70 seconds after initialization. The episode ended at 13.625 seconds with health `-3`.

The death is part of the result: after the fifth kill there was no target in view, the local body rotated
to scan, and an off-screen Demon most likely continued melee attacks. The log did not record attacker ID,
so the exact individual is unknown.

> Cloud LLM killed five enemies, then got bitten from behind.

## Fair claims

This run supports:

> A general-purpose cloud LLM read structured enemy position and chose every individual ViZDoom
> trigger pull with a one-character response while the game continued to run.

It does not support:

- end-to-end pixel perception
- complete FPS control
- human superiority under equal sensory and motor conditions
- stable 200 ms latency
- a raw-thinking speedup in the successful `direct-bit` run

Human simple and choice reaction-time studies make the 256--274 ms range interesting, but the LLM
received structured labels and local aim assistance. The accurate comparison is that cloud round-trip
latency entered a human-like reaction-time band under these assisted conditions.

## Runtime bugs found before the final run

- A pending FIRE originally could be invalidated by capturing the next observation first. The loop now
  consumes a fresh one-shot decision at the tick boundary before starting the next cloud observation.
- `provider.order=[Groq]` did not prevent OpenRouter fallback. The runtime now supports
  `allow_fallbacks=false` and exposes `--no-provider-fallback`.
- A cost guard once launched repeated failing tasks after stopping. The first budget stop now disables
  further launches.
- API errors are sanitized before logging. API keys are never written to run artifacts.

## Next experiment: four actions

The next milestone removes local horizontal tracking and lets the cloud model choose one bounded action
per fresh observation:

```text
WAIT / LEFT / RIGHT / FIRE
```

The unpaused world, latest-observation arbitration, one-shot semantics, and freshness deadline stay.
This makes it possible to measure how much of the current success came from task decomposition without
falling back to a synchronous, frozen game.
