# V4各10回実験: 一文字運動野

実験日: 2026-08-19

## 結論

V4は、一つのCloud LLM policyだけでViZDoomの探索・左右旋回・発砲を完走した。
paired seed 7〜16の10 runで公式KILLCOUNTは35、平均3.5だった。V3の15 killには
10 / 10 seedで勝ち、35 Hzのlocal追尾を持つV2の54 killには0勝9敗1分だった。

ただし35のうち1 killは、弾薬もHITCOUNTも増えずKILLCOUNTだけ増えた。したがって
記事では「公式score 35、HITCOUNT 34」と分ける。V4が人間のように
画面を理解した実験でもない。ViZDoom labelsからlocal側が最大面積の敵を選び、
`visible / x / ammo`へ構造化した後の6択制御である。

## V4は誰が何を決めるのか

```text
ViZDoom (35 Hz、推論中も進む)
  │
  ├─ local知覚: labelsから最大面積の敵を選び v/x/ammo を作る
  │
  └─ 0.1秒ごとに同じLLM policyを最大3 request重ねる
          │
          └─ 最初の一文字 0〜5
                 │
                 └─ local protocol層
                      ├─ 文法、400 ms、観測番号だけ検査
                      └─ tokenに固定された1/2/5 tickをそのまま実行
```

3 laneは3人格ではない。同じmodel、同じprompt、同じpolicyを時間差で走らせ、
返った中で観測番号が最も新しい有効tokenが身体を取る。

| token | LLMが選ぶ操作 | localで固定された長さ |
|---:|---|---:|
| `0` | WAIT | 1 tick |
| `1` | LEFT_SHORT | 2 ticks、約57 ms |
| `2` | LEFT_LONG | 5 ticks、約143 ms |
| `3` | RIGHT_SHORT | 2 ticks、約57 ms |
| `4` | RIGHT_LONG / 敵不在時の探索 | 5 ticks、約143 ms |
| `5` | FIRE | 1 tick、約29 ms |

local側はFIRE直前に中央かを再確認しない。LEFT / RIGHTを敵の現在位置で補正しない。
weapon cooldown中のFIREを再試行しない。誤ったtokenも、期限内ならそのまま実行する。
正解ruleを計算する関数はprobe、mock、事後採点にだけ使い、live action pathは参照しない。

## 条件

- model: `meta-llama/llama-3.1-8b-instruct`
- route: OpenRouter経由Groq、fallbackなし、`sort=latency`
- reasoning: disabled、temperature 0
- output: visible出力の最初の非空白ASCII `0`〜`5`
- scenario: `defend_the_center`
- duration: 最大15秒、死亡時はその場で終了
- paired seed: 7〜16。V2 / V3と同じ
- observation interval: 0.10秒
- concurrent lane: 3
- token最大年齢: 400 ms
- world: 35 Hzで推論中も停止しない
- game前に6 tokenを一つずつ問い合わせ、6 / 6でなければ操作権を渡さない
- 上限: game 180 request、`$0.025` / run

seed 7 / 8は最終promptを固定した直後の確認runで、そのままbenchmarkへ採用した。
seed 9〜16もcode、prompt、provider、制御値を変えず続けた。10 runのstartup probeは
すべて初回6 / 6、game API errorは0だった。

## 各run

| seed | V2 kill | V3 kill | V4 score kill | V4 hit | tick | 平均判断ms | game req | 正解 / 判断 | 棄却 | 実弾 | 実費 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 7 | 5 | 2 | 4 | 4 | 498 | 260.9 | 113 | 106/110 | 4 | 6 | $0.00115791 |
| 8 | 7 | 2 | 4 | 4 | 494 | 261.9 | 112 | 101/109 | 1 | 6 | $0.00114710 |
| 9 | 5 | 1 | 2 | 2 | 422 | 256.6 | 94 | 87/91 | 5 | 6 | $0.00096757 |
| 10 | 4 | 1 | 3 | 3 | 500 | 213.0 | 112 | 102/110 | 6 | 8 | $0.00115771 |
| 11 | 6 | 0 | 2 | 2 | 398 | 267.6 | 89 | 79/87 | 2 | 5 | $0.00092808 |
| 12 | 8 | 3 | 5 | 5 | 506 | 263.2 | 120 | 111/118 | 0 | 10 | $0.00123769 |
| 13 | 5 | 1 | 4 | 4 | 478 | 264.3 | 104 | 97/103 | 4 | 9 | $0.00108754 |
| 14 | 5 | 2 | 5 | 4 | 498 | 213.3 | 114 | 103/113 | 3 | 9 | $0.00118724 |
| 15 | 4 | 1 | 3 | 3 | 506 | 261.7 | 107 | 99/105 | 6 | 10 | $0.00109710 |
| 16 | 5 | 2 | 3 | 3 | 462 | 259.2 | 107 | 99/105 | 0 | 6 | $0.00109865 |

`score kill`はViZDoom `KILLCOUNT`、`hit`は`HITCOUNT`。seed 14の差1が、
monster infightingと思われるscoreだけのkillである。

## Replay

seed 12はKILLCOUNTとHITCOUNTがともに5で、今回のV4最高成績と直接hitが一致した。
字幕の`MOTORLEFT / MOTORRIGHT / MOTORFIRE`は、local追尾ではなくCloud LLMが返した
一文字tokenから実行されたactionである。

![V4一文字運動野のseed 12、5 hit・5 kill全編replay](assets/v4-direct-motor-seed12-5-kills.gif)

## 集計

| 指標 | V2 | V3 | V4 |
|---|---:|---:|---:|
| completed run | 10 | 10 | 10 |
| score kill合計 | 54 | 15 | **35** |
| score kill平均 / 中央値 | 5.4 / 5.0 | 1.5 / 1.5 | **3.5 / 3.5** |
| score kill範囲 | 4〜8 | 0〜3 | **2〜5** |
| game秒あたりscore kill | 0.401 | 0.133 | **0.257** |
| 平均生存game秒 | 13.47 | 11.27 | **13.61** |
| 15 game秒到達 | 2 / 10 | 0 / 10 | **0 / 10** |
| run平均判断latency | 253.0 ms | 282.1 ms | **252.2 ms** |
| game request | 312 | 1,348 | **1,072** |
| game request / 秒 | 2.32 | 11.96 | **7.88** |
| API request error | 0 | 0 | **0** |
| 古い・期限切れ棄却 | 77 | 464 | **31** |
| coalesced observation | 3 | 42 | **83** |
| 意味判断正解 | 204 / 207受理判断 | 1,224 / 1,302受信票 | **984 / 1,051判断** |
| FIRE tick | 71 | 30 | **105** |
| ammo消費 | 62 | 28 | **75** |
| hit / score kill | 54 / 54 | 15 / 15 | **34 / 35** |
| 実弾あたりhit | 87.1% | 53.6% | **45.3%** |
| WAIT tick比率 | 35.2% | 60.2% | **27.3%** |
| OpenRouter報告実費 | `$0.00138016` | `$0.00675922` | **`$0.01106659`** |

V4はV3よりgame requestを20.5%、棄却を93.3%、WAIT比率を32.9 percentage point
減らし、score killを133.3%増やした。一方、promptが長く生存時間も延びたため、
request数が減っても実費はV3の1.64倍になった。V2は発砲判断時だけCloudへ聞き、
左右追尾はlocalなので、request数・費用・命中率を対等なpolicy比較とは扱わない。

game秒は3版とも`tick / 35`で計算した。集計中、旧`summary.duration_ms`がgame終了後の
GIF encode時間まで含む計測バグを発見したためである。control、tick、killには影響しない。
V4 branchではactive wall timeをGIF前に確定し、別に`simulation_duration_ms`も出すよう修正した。

## 反応時間

`判断latency`はOpenRouter画面のprovider TTFTではなく、観測captureから最初の有効な
一文字がclientへ届くまでである。

| 区間 | 結果 |
|---|---:|
| 観測 → 受理token 最短 / p50 / p95 / p99 / 最長 | 156 / 250 / 313 / 359 / 391 ms |
| FIRE token到着 → 次のFIRE tick p50 / p95 | 31 / 47 ms |
| FIRE元観測 → 実FIRE tick p50 / p95 | **281 / 328 ms** |

したがって「Cloud LLMが250 msで理解した」と断言するより、正確には
「構造化観測から有効なmotor tokenが中央値250 msで届き、FIRE入力は中央値281 msで
ゲームへ入った」である。人間の単純反応時間と同じ桁だが、知覚条件も運動条件も違う。

## 本当に誤答も操作になったか

1,051判断中67件がprompt上の正解と異なり、そのうち65件は期限内だったため採用された。
local側は訂正していない。

| 期待 → 実際 | 採用された誤答 |
|---|---:|
| LEFT_SHORT → LEFT_LONG | 29 |
| RIGHT_SHORT → FIRE | 12 |
| LEFT_SHORT → FIRE | 8 |
| RIGHT_SHORT → RIGHT_LONG | 8 |
| RIGHT_LONG → RIGHT_SHORT | 3 |
| LEFT_LONG → RIGHT_LONG | 2 |
| RIGHT_LONG → FIRE | 2 |
| FIRE → LEFT_SHORT | 1 |

特に短い補正を長い旋回へ変えた29件と、まだ右にいる敵へFIREした12件は、V4の
ふらつきとmissとしてreplayへ残った。これは成績を落とす一方、「実はlocal controllerが
正解を選び、LLMは許可だけ」という抜け道がないことの観測証拠でもある。

## 身体の内訳

| 項目 | 10 run合計 |
|---|---:|
| 受理token | 1,020 |
| 新tokenによるpulse中断 | 447 |
| RIGHT_LONG選択 / 実行tick | 634 / 2,487 |
| RIGHT_SHORT選択 / 実行tick | 53 / 101 |
| LEFT_LONG選択 / 実行tick | 179 / 679 |
| LEFT_SHORT選択 / 実行tick | 46 / 89 |
| FIRE選択 / 実行tick | 108 / 105 |
| WAIT選択 / WAIT実行tick | 0 / 1,301 |

弾が尽きなかったため明示的WAIT tokenは0件だった。1,301 WAIT tickは、LLMがWAITを
選んだのではなく、新しい有効pulseを待つ隙間で全buttonを離したdead-man状態である。
105 FIRE tickに対して実弾は75発。残りはweapon cooldown中の空振り入力で、local再試行は
していない。

## ボトルネック

### 1. 250 ms前の座標を見て固定pulseを出す

FIREまで中央値281 msかかる。敵と照準はその間も動くため、75発中34 hitに留まった。
V3より多く撃つことでkillは増えたが、一発の精度はV3の53.6%より低い。

### 2. 8B modelは明示ルールでも6.4%間違える

左右の符号より、短 / 長の境界で混乱した。これはlocal correctionを入れれば簡単に消せるが、
それをするとV2へ戻るためV4では残した。

### 3. 0.1秒指定でも実効7.88 request / game秒

3 laneが遅いrequestで埋まり、83観測をcoalesceした。pipelineは世界を止めないが、同じ
decodeの途中へ新観測を差し込めるわけではない。各requestはcapture時点の静止した情報を見る。

### 4. 一文字より教科書のほうが重い

回答は一文字でも、6択を安定させるsystem promptは約196 prompt tokenある。
V3よりrequestは少ないのに費用は高い。次はprompt cache、短い専用model、fine-tuneの順で
「一文字のために教科書一冊を毎回郵送する」を止めたい。

### 5. まだ視覚Agentではない

local側がViZDoom labelsから最大面積のmonsterを選び、座標へ圧縮している。V4は公平な
motor-control実験だが、pixel認識、複数敵の戦術、武器選択、移動経路は解いていない。

## Probeと費用

最初の条件文だけのpromptはstartup suite 6問中3問を間違え、gameへ入る前に停止した。
few-shotへ直した独立probeは6 / 6、その後benchmarkの10 suiteもすべて6 / 6だった。

- 失敗probe: `runs/20260819-015308-09c01c25`、`$0.00004811`
- 修正後probe: `runs/20260819-015346-729491dc`、`$0.00005981`
- benchmark 10 run: game 1,072 + probe 60 request、`$0.01106659`
- V4 live作業合計: 1,144 request、**`$0.01117451`**

失敗の詳細は[六択を一行で教えたら三問落とした](v4-probe-language-failure.md)へ。

## Artifact directories

`runs/`はGit管理外。各directoryに`events.jsonl`、`summary.json`、`episode.gif`がある。

- seed 7: `20260819-015414-157ce3c5`
- seed 8: `20260819-015519-1d65e4fb`
- seed 9: `20260819-015724-e4536c4d`
- seed 10: `20260819-015740-f571170d`
- seed 11: `20260819-015757-9299af9b`
- seed 12: `20260819-015812-4bb8ce32`
- seed 13: `20260819-015830-ba55a2d4`
- seed 14: `20260819-015848-41cb880e`
- seed 15: `20260819-015906-e17a75d9`
- seed 16: `20260819-015924-231578b7`

## 判定

V4は「Cloud LLMにViZDoomをやらせた」と呼んでよい。ただし省略しない正式版は、
**「ViZDoomの構造化敵座標を見たCloud LLMが、unpaused worldで全motor tokenを選んだ」**。
raw pixelsを見たわけではなく、強いlocal追尾にも勝っていない。それでもV3の四人会議より
一人へ一文字で身体を渡したほうが2.33倍倒せた。くだらないが、かなりちゃんと動いた。
