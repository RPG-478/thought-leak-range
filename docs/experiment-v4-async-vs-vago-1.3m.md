# 非同期V4 vs VAGO MultiVec 1.3M

## 結論

同梱weightsをこちらのPCで10 episode再実行すると、VAGO MultiVec 1.3Mは
**156 kill、平均15.6 kill**だった。非同期V4 flat-4の40 kill、平均4.0 killに対して
episode scoreは**3.9倍**で、専用local modelの明確な勝ちである。

ただし、これは同条件の直接対決ではない。VAGOの公開runnerは`PLAYER` modeで
`state取得 → 推論 → make_action(4 tic)`を直列実行する。推論中はゲーム時間が進まない。
V4は`ASYNC_PLAYER`相当の独立clockで、Cloudを待つ約233 msにも世界が35 Hzで進む。

したがって、この比較が答えるのは次の二つである。

- 「公開1.3M modelは本当に強いか」: **Yes。こちらでも平均15.6 killを再現した**
- 「Cloud LLMは止まらない世界でも操作できるか」: **Yes。ただし現状は平均4.0 killで大差がある**

## 数値

| 項目 | 非同期V4 flat-4 | VAGO 1.3M・今回再現 | VAGO公開値 |
|---|---:|---:|---:|
| episode | 10 | 10 | 10 |
| total kill | 40 | **156** | **178** |
| mean kill | 4.0 | **15.6** | **17.8** |
| mean survival | 12.51秒 | **351.7 decision ≒ 40.19秒** | 388 decision ≒ 44.34秒 |
| max survival | 17.17秒 | **525 decision = 60秒** | 525 decision = 60秒 |
| mean decision latency | 232.8 ms | 216.2 ms | **31 ms** |
| p95 latency | 344 ms | 279.3 ms | 未掲載 |
| 推論中のworld | **35 Hzで進む** | **止まる** | **止まるrunner** |

今回のPCではTorch CPU推論が公開31 msより大幅に遅く、平均216.2 msだった。それでも
VAGO runnerではその216 msがgame tickを一つも消費しない。`--realtime`は推論後に
4 / 35秒へ足りない分をsleepするだけで、推論とgame clockを並行にはしない。

## なぜ1.3M版が強いのか

単に小さいから速い、だけではない。

1. 31K frameの人間プレイを教師にしたDoom専用policyである
2. 40×25 ASCIIに加えて16段階depthを受け取る
3. `shoot / move_forward / turn_left / turn_right`を複数同時に出せる
4. 公開runnerでは推論中に敵・cooldown・時計が進まない
5. local推論なのでnetwork jitterがない

今回のaction分布でも、単独actionより`move_forward+turn_left`などの複合actionが支配的だった。
一方V4は汎用Cloud LLMに短い構造化labelを渡し、WAIT / LEFT / RIGHT / FIREの一つだけを
選ばせる。前進もdepthも同時押しもない。VAGOは「速い専用脳」に加え、身体と入力も有利である。

## それでもV4が示したこと

VAGOが否定したのは、公開baselineのようにLLMを同期loopへ素直につなぐ方式である。
非同期V4は、その評価ロジックとは別の問いを実装した。

> 遅いCloud LLMの判断を待つ間も世界を止めず、複数requestを重ね、期限付きの一文字を
> 身体へ流せば、汎用LLMはFPSで一体も倒せないのか。

答えは「倒せる。10本で40体。ただし専用modelにはまだ大敗」である。
反撃点はscoreではなく、**同期停止をCloud LLMの本質的限界として扱えない**ことにある。

## 再現条件と注意

- upstream: `VAGOsolutions/SauerkrautLM-Doom-MultiVec`
- commit: `b4c3fdfd47cff530f69e8808eae4cc5545671772`
- bundled model: `models/doom-multivec-trained`、約1.3M parameters
- scenario: `defend_the_center`
- `--episodes 10 --frame-skip 4 --realtime`
- Python 3.12.10 / torch 2.13.0+cpu / transformers 5.15.1 / vizdoom 1.3.0
- seed指定なし。V4 seeds 7〜16とのpaired comparisonではない
- 日本語workspace pathでViZDoom `load_config`が`UnicodeDecodeError`になったため、
  cfgとWADだけを内容無変更でASCII一時pathへ複製した

集計JSONは[こちら](results/vago-1.3m-reproduction-2026-08-21.json)。V4の各seedと正式条件は
[V4 Async × flat-4](experiment-v4-async-flat-4.md)にある。
