# V4 Async × flat-4

## 一言

同期世界で平均26.3 killを出したV4-S flat-4から、**世界停止だけを外した**。
同じCloud LLMが考えている約233 msのあいだも、敵と35 Hzの時計は進み続ける。

## 条件

- model: `meta-llama/llama-3.1-8b-instruct`
- provider: Groq via OpenRouter、fallbackなし、latency routing
- scenario: `defend_the_center`
- world / motor body: `clock-thread` / `clock-thread`
- seed: 7〜16、10 episode
- duration: 最大60 wall-clock秒、死亡終了
- observation: 0.10秒、3 lane
- 全tokenを4 native ticへ統一: `--motor-flat-pulse-ticks 4`
- token TTL: 400 ms
- local aim補正、方向補正、side leaseなし
- 正式runはGIF取得なし。全runで31.5 Hz以上を確認

## 正式結果

| seed | 同期V4-S kill | 非同期kill | 生存秒 | 実効Hz | 平均判断ms |
|---:|---:|---:|---:|---:|---:|
| 7 | 30 | 2 | 10.64 | 34.40 | 239.8 |
| 8 | 25 | 5 | 11.44 | 33.92 | 191.0 |
| 9 | 28 | 3 | 10.22 | 34.45 | 256.2 |
| 10 | 28 | 5 | 14.64 | 32.10 | 247.4 |
| 11 | 26 | 2 | 10.11 | 35.02 | 245.2 |
| 12 | 27 | 5 | 12.28 | 35.01 | 266.7 |
| 13 | 24 | 3 | 11.48 | 35.00 | 256.3 |
| 14 | 22 | 3 | 11.55 | 34.82 | 202.4 |
| 15 | 29 | 7 | 17.17 | 35.00 | 194.3 |
| 16 | 24 | 5 | 15.55 | 34.35 | 245.4 |
| **計 / 平均** | **263 / 26.3** | **40 / 4.0** | **12.51** | **34.41** | **232.8** |

- 非同期は同期scoreの15.2%。平均killは84.8%低下
- 10 / 10死亡、最小2 / 最大7 kill
- 1,057判断、913意味正解、正解率86.38%
- latency: mean 232.8 / p50 219 / p95 344 ms
- request error 0、OpenRouter報告実費 `$0.01112201`
- 1,007 tokenをqueue、983 commit、24件はcommit前に新判断で置換
- 22件は観測期限切れ、16件は到着順逆転で棄却
- FIRE 289判断 / 1,011 native tic、観測上160発消費、39 hit

判断正解率は同期版76.55%よりむしろ高い。それでもkillは激減した。したがって主因は
LLMの意味理解ではなく、**観測から返答まで平均約8 native tic進む時間差**と考えるのが自然である。
Flat-4は「筋肉が長すぎる」問題を直すが、届いた命令が古い問題は直さない。

## 途中で踏んだ面白い罠

最初は指定どおり3 process並列で10本を走らせたが、一部ViZDoomが22.9〜30.5 Hzへ低下した。
さらに既存判定は「死亡完走なら低Hzでもvalid」という誤った条件だった。判定を修正し、
31.5 Hz未満の7 seedを単独再走して上表へ差し替えた。

つまりCloud latencyを測っていたら、ローカルの地獄時計までCPU混雑で遅くなった。
正式runでは今後、死亡しても35 Hz判定を免除しない。

## GIFについて

clock-threadでの追加screen readは時計を遅くし得るため、正式数値runと録画runを分離した。
10本のGIFは[visual-only replay index](replays/2026-08-21-v4-async-clock-flat-4-visual-only/README.md)に置く。
GIF側のkillやHzは挙動観察専用で、上表のbenchmark値へ混ぜない。

## 次の一手

Flat-4は残す。次に触るべきはpulse長ではなく「約8 tick古い方向命令」である。
最小候補は、到着したLEFT / RIGHTを現在の最接近敵座標で再検証し、既に中心線を越えていたら
破棄または反転すること。ただしこれはlocal aim assistになり得るため、LLM完全操作版では
まず観測時の位置と速度からLLM自身に到着時位置を予測させる比較を先に置く。
