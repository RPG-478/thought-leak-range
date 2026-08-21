# VAGO 1.3MをCloudと同じ200 msまで遅くする

## 結論

VAGO 1.3Mのmodel、観測、action policyは変えず、観測からaction到着までを最低200 msへ
人工的に遅らせた。世界はその間も35 Hzで進む。

結果は**177 kill・平均17.7から、42 kill・平均4.2へ低下**した。同じseedのCloud V4は
40 kill・平均4.0である。速い専用modelとCloud LLMは全く別のpolicyなのに、判断を約7 tic
古くするとほぼ同じscore帯へ着地した。

| 条件 | action age | kill合計 / 平均 |
|---|---:|---:|
| VAGO 1.3M / 通常T4 | 1.049 tic | **177 / 17.7** |
| VAGO 1.3M / 200 ms floor | **7.038 tic** | **42 / 4.2** |
| Cloud V4 / 実測232.8 ms | 約8 tic | **40 / 4.0** |

1.3Mは人工遅延だけで76.3%失点した。これは「Cloud V4が弱い主因は汎用LLMの理解不足」より、
**正しいactionでも届くころには古い**という説明を強く支持する。

## paired seed

| seed | 1.3M通常 | 1.3M 200 ms | Cloud V4 |
|---:|---:|---:|---:|
| 7 | 17 | 4 | 2 |
| 8 | 24 | 5 | 5 |
| 9 | 9 | 4 | 3 |
| 10 | 18 | 4 | 5 |
| 11 | 21 | 6 | 2 |
| 12 | 18 | 1 | 5 |
| 13 | 21 | 3 | 3 |
| 14 | 18 | 6 | 3 |
| 15 | 16 | 3 | 7 |
| 16 | 15 | 6 | 5 |
| **計 / 平均** | **177 / 17.7** | **42 / 4.2** | **40 / 4.0** |

200 ms版はCloudへ5 seedで勝ち、3 seedで負け、2 seedで同点だが、10本平均差は0.2しかない。
両者の入力とaction protocolが違うため勝敗数をmodel能力比較には使わない。重要なのは、1.3M自身の
paired ablationで13.5 kill落ちたことと、落下先がCloudのscore帯だったことである。

## 実験条件

- Google Colab / Tesla T4
- seed 7〜16、10 episode、最大2100 native tic
- ViZDoom worldは専用threadで35 Hz継続
- modelの実計算は平均29.24 ms
- `sleep(max(0, observation_time + 200 ms - now))`でaction deliveryを遅延
- 28 msへ200 msを追加するのではなく、観測から到着までの合計を最低200 msにする
- inference workerは待機中も次の推論を開始しないため、遅い推論のthroughputも模擬
- latest-only observation queue、4 tic observation、4 tic action pulse
- clock valid 10 / 10、平均35.045 Hz、error 0
- GIF取得なし

200 msは7 native ticに相当する。実測action ageは平均7.038 tic、時間換算で約201.1 msだった。
したがって、人工sleepがgame clockを止めたり、単に設定だけ記録された結果ではない。

生ログは[`vago-1.3m-async-200ms-colab-2026-08-21.json`](results/vago-1.3m-async-200ms-colab-2026-08-21.json)。
runnerには再利用可能な`--minimum-action-latency-ms`を追加し、実model計算時間と
observation-to-action latencyを別々に記録する。

## 公平性

これは「VAGOとCloudの知能が同じ」という証明ではない。VAGOはASCII＋depthとmulti-hot action、
Cloud V4はlabel＋一文字actionであり、身体も入力も異なる。またCloudの平均232.8 msに対して、
今回のfloorは200 msなのでVAGO側が約33 ms新しい。

それでも、同じVAGO modelのpaired条件で17.7→4.2へ落ちた事実は動かない。今回分離できたのは
model知能ではなく、**action鮮度の因果効果**である。

## 一言でいうと

> 1.3Mの専用脳から賢さを奪わず、反射神経だけCloud並みにしたら、戦績までCloud並みになった。

## 次のIssue候補: latency cliffを描く

この結果は一点比較でも面白いが、Issueとしては「どこから崩れるか」を募集できる。

- 目標latency: 30 / 60 / 100 / 150 / 200 / 233 / 300 ms
- 固定delayとCloud実測jitterを分ける
- meanだけでなくp95、action age、neutral tic、観測置換を追う
- 古いactionをそのまま実行／破棄／現在位置へ補正、の三条件を比べる
- scoreが滑らかに落ちるのか、特定のnative ticを越えると崖になるのかを見る

Issueの核になる問いは、**「FPS agentの能力はparameter数より、何tick前の自分を操作しているかで
決まるのではないか？」**である。
