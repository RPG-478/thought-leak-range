# Prior art and the remaining odd gap

This project is not the first attempt to make an LLM play DOOM or ViZDoom.

## Direct precedent: cloud LLMs in ViZDoom

The 2026 arXiv preprint
[Playing DOOM with 1.3M Parameters: Specialized Small Models vs Large Language Models for Real-Time Game Control](https://arxiv.org/abs/2604.07385)
and its public implementation,
[SauerkrautLM-Doom-MultiVec](https://github.com/VAGOsolutions/SauerkrautLM-Doom-MultiVec),
benchmark cloud LLMs directly in ViZDoom's `defend_the_center` scenario. The paper's main contribution is a
1.3M-parameter specialized model, but its baselines are highly relevant here.

All agents receive a 40x25 ASCII view plus a quantized depth map and choose among `shoot`,
`move_forward`, `turn_left`, and `turn_right`.

| Cloud model | Reported result | Mean latency |
|---|---:|---:|
| GPT-4o-mini | 0 frags / 10 episodes | 646 ms |
| Gemini Flash Lite via OpenRouter | 8 frags / 10 episodes | 920 ms |
| Qwen3.5-27B | 2 frags / 3 episodes | 13.3 s |
| Nemotron-120B | 3 frags / 5 episodes | 8.9 s |

These are self-reported, non-peer-reviewed project numbers from its
[model card](https://huggingface.co/VAGOsolutions/SauerkrautLM-Doom-MultiVec-1.3M).

### Important timing difference

Its public [benchmark loop](https://github.com/VAGOsolutions/SauerkrautLM-Doom-MultiVec/blob/main/scripts/benchmark.py)
uses synchronous ViZDoom `PLAYER` mode and follows this order:

```text
get_state()
  -> wait for the complete cloud API response
    -> make_action(buttons, frame_skip=4)
      -> sleep only when inference was faster than the target interval
```

Because the game is stepped by `make_action`, the world does not keep advancing during a slow cloud
request. Calling the option `--realtime` paces a fast model so it does not outrun 35 Hz, but the code does
not implement an asynchronous unpaused world for a 646 ms--13.3 s request. We confirmed this against
upstream commit `b4c3fdf` rather than relying on code reading alone: 0 ms and 650 ms versions of the same
policy produced bit-identical RGB and depth trajectories, steps, kills, and HP. See the
[timing probe](vago-sync-probe.md).

Latency Kills chooses the opposite tradeoff: perception and control are initially easier, but the
world remains live and stale cloud decisions are rejected.

| | Sauerkraut cloud baseline | Latency Kills `direct-bit` |
|---|---|---|
| World during API call | Synchronous / not stepped | Unpaused at 35 Hz |
| Perception | ASCII plus depth | Structured ViZDoom labels |
| Control | Four actions | Trigger only; local LEFT/RIGHT tracking |
| Response | Completed action text | First strict visible `1` or `0` |
| Staleness | No observation-age guard | Latest observation plus 300 ms deadline |
| Representative result | Gemini 0.8 frag/episode at 920 ms | Five kills in one run; FIRE at mean 274 ms |

The results are not directly comparable because the observation and action spaces differ.

### What V3/V4 rebut — and what they do not

V3 and V4 remove the local aiming used by `direct-bit`. Cloud decisions choose waiting, turning, and
firing while the world continues at 35 Hz. V3 uses four action specialists; V4 uses one six-token
policy over three staggered request lanes. In ten paired 15-second runs, V3 averaged 1.5 kills and V4
averaged 3.5 official kills, with mean V4 decision latency of 252.2 ms.

This is a clear architectural counterexample to the broad claim that cloud/general LLM latency makes
live Doom control impossible. It is **not** evidence that V4 beats VAGO's 1.3M specialized winner,
which reports 178 frags across ten episodes at 31 ms.

There is also a method mismatch in the published baseline. The paper attributes LLM failure partly to
enemies moving during inference, but the public code uses synchronous `PLAYER` mode and calls
`make_action()` only after the blocking API response returns. Under ViZDoom's documented synchronous
semantics, game ticks do not advance during that wait. The baseline therefore measures a paced
synchronous agent, not an unpaused cloud controller.

Important remaining confounds:

- VAGO uses 40x25 ASCII plus depth; V4 currently receives privileged structured label-derived state.
- VAGO exposes four actions including forward movement; V4 is currently a turret-like turn/fire task.
- Episode duration, seeds, and kill attribution are not aligned, so frag totals are not directly comparable.

We have now made the first clock-only ablation by running the same current V4 policy under both
adapters. On fresh seed 12, unpaused V4 scored two kills while the stopped version scored six; all
158 stopped request waits consumed zero game tics, WAIT fell from 106 to three tics, and pulse
preemption fell from 38 to zero. This is one seed and still uses V4's structured labels and turret action
space, so it isolates the clock scaffold rather than comparing against VAGO's model. See the
[V4-S experiment](experiment-v4-vago-sync.md).

The remaining fully aligned comparison is the same cloud model, ASCII+depth input, action set, seeds,
and episode limits under two adapters: VAGO's blocking synchronous loop and V4's overlapping,
TTL-guarded, one-token loop.

## Other close systems

- [Will GPT-4 Run DOOM?](https://arxiv.org/abs/2403.05468) used GPT-4V and GPT-4 through a
  DOOM-specific scaffold. It demonstrated combat and navigation without fine-tuning, but inference was
  far from real-time and the paper suggested ViZDoom as possible future benchmark infrastructure.
- [VideoGameBench](https://arxiv.org/abs/2505.18134) evaluates general VLMs in games including DOOM II
  and explicitly measures the stale-action problem. It also provides paused inference conditions.
- [Game-TARS](https://arxiv.org/abs/2510.23691) uses sparse reasoning and native keyboard/mouse actions,
  but is a game-trained multimodal agent rather than an untouched cloud LLM.
- [Pixels2Play](https://arxiv.org/abs/2510.16774) is a local vision-action policy designed for 20 Hz
  control, not a general cloud language model.
- [NitroGen](https://arxiv.org/abs/2601.02427) is a fast game action foundation model trained on large
  gameplay datasets. Its published evaluation is synchronous and its role is closer to a System 1 body.

## What remains distinct

The broad claim "a cloud LLM played ViZDoom" has prior art and should not be presented as a world first.
The narrower combination not found in the reviewed public implementations is:

1. the ViZDoom world continues at 35 Hz during cloud inference;
2. multiple requests may complete out of order;
3. every result is bound to an observation generation;
4. stale results expire before actuation;
5. the first valid streamed decision can become one bounded action without waiting for prose;
6. the successful run is measured by observation-to-motor latency, not only API latency.

A careful one-line positioning is:

> Cloud LLM control of ViZDoom already existed; this project tests whether it can act before a live,
> unpaused observation becomes stale.
