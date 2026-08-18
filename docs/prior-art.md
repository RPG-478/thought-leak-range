# Prior art and the remaining odd gap

This project is not the first attempt to make an LLM play DOOM or ViZDoom.

## Direct precedent: cloud LLMs in ViZDoom

The 2026 open-source project
[SauerkrautLM-Doom-MultiVec](https://github.com/VAGOsolutions/SauerkrautLM-Doom-MultiVec)
benchmarks cloud LLMs directly in ViZDoom's `defend_the_center` scenario. Its main contribution is a
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
not implement an asynchronous unpaused world for a 646 ms--13.3 s request. This is an inference from the
published code, not a claim made by its authors.

Thought Leak Range chooses the opposite tradeoff: perception and control are initially easier, but the
world remains live and stale cloud decisions are rejected.

| | Sauerkraut cloud baseline | Thought Leak Range `direct-bit` |
|---|---|---|
| World during API call | Synchronous / not stepped | Unpaused at 35 Hz |
| Perception | ASCII plus depth | Structured ViZDoom labels |
| Control | Four actions | Trigger only; local LEFT/RIGHT tracking |
| Response | Completed action text | First strict visible `1` or `0` |
| Staleness | No observation-age guard | Latest observation plus 300 ms deadline |
| Representative result | Gemini 0.8 frag/episode at 920 ms | Five kills in one run; FIRE at mean 274 ms |

The results are not directly comparable because the observation and action spaces differ.

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
