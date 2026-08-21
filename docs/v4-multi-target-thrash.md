# V4失敗replay — 敵が二体になったら標的が左右へ瞬間移動した

これはV4一文字運動野の実Cloud runで、敵が増えたあと左右旋回を繰り返し、
0 killのまま倒された失敗例である。

![V4 Cloud LLMが複数敵の間で照準を往復して倒されるreplay](https://github.com/RPG-478/latency-kills/releases/download/replays-highlights-2026-08-21/v4-cloud-multi-target-thrash-seed12-0-kills.gif)

## Run

- mode: `live / direct-motor`
- model: `meta-llama/llama-3.1-8b-instruct`
- provider: Groq via OpenRouter
- seed: 12
- 平均判断遅延: 283.7 ms
- 判断精度: 52 / 53
- 結果: 0 hit / 0 kill / health 0

LLMの分類精度は悪くない。それでも一発しか撃てず、当たらなかった。

## 見つかった標的スイッチ

観測器は複数の敵をLLMへ列挙していない。monster候補のうち画面上の面積が最大の
一体だけを選び、`v / x / a`を一組送っている。ところが二体の見かけの大きさが
入れ替わると、選ばれる`target_id`も入れ替わる。

```text
obs31: target_id=3  x=-0.800
obs32: target_id=6  x=+0.716
obs33: target_id=3  x=-0.750
```

3 laneには、それぞれ異なる時点の「完全な命令」が残る。この切り替わりでは
LEFTとRIGHTがCloud遅延を挟んで交互に到着し、V4の強いLONG pulseが逆に往復運動を
増幅する。敵が一体のときに強かったsample-and-holdが、標的identityが不安定になると
「さっき選ばれた別の敵を長く追う」装置になる。

## 次の最小修正候補

入力をさらに減らす必要はない。すでに一体だけである。必要なのは、近い敵を一度選んだら
数観測だけidentityを固定するtarget lock / hysteresisである。

- 現在のtargetが見えている間は、少し大きい別敵へ即座に乗り換えない
- 別敵が十分に大きい、または現在targetが消えた場合だけ切り替える
- Cloudには従来どおり一体分の`v / x / a`だけを送る
- localが照準方向を決めるのではなく、**どの敵について尋ねるか**だけを安定させる

これはlocal aim assistではない。LLMがLEFT / RIGHT / FIREを決める境界は変えず、
同時に三人の敵を指さす壊れた観測だけを防ぐ。

## 2026-08-21 実装と反証

最小修正として、現在の`target_id`が画面に存在する限り必ず維持し、消えた場合だけ
最大面積の敵へ切り替える厳格なidentity lockを実装した。別敵が何倍大きくなっても、
現在targetが見えている間は切り替えない。単体テストでは左右の候補が入れ替わっても
同じIDを返すことと、現在IDが消えた場合の切り替えを固定した。全73 testが通過した。

しかし実Cloudのseed 12では、標的lockだけによる戦績改善は再現しなかった。

| 条件 | 平均判断遅延 | kill | 終了health | tick |
|---|---:|---:|---:|---:|
| 旧selector相当（毎回最大面積） | 250.2ms | 3 | 0 | 366 |
| 1.5倍hysteresis | 244.4ms | 3 | -4 | 412 |
| 厳格visible-ID lock | 239.7ms | 3 | 0 | 366 |
| 1.5倍lockの高速だった一回 | 191.6ms | 6 | 68 | 525 |

別seed 7〜9の厳格lock前の試行は6 / 8 / 5 killだったが、平均latencyも約247msで、
旧Formal D V4の約372msより大幅に速かった。したがって旧2 / 4 / 4 killとの差を
target lockの効果だけに帰属してはいけない。

現時点の結論は二つ。

1. target identityの左右反復は実在する観測バグで、厳格lockにより構造的に止まった。
2. 敵が増えたときの死亡を主に決めているのは、target選択よりCloud判断速度である可能性が高い。

「見つけたバグを直したら強くなった」ではなく、「見つけたバグは本物だったが、ボスは別にいた」。
この失敗replayはその切り分けまで含めて残す。

## GIF再読: 本当のボスは標的選択よりovershoot

GIFを人間が見直すと、より直接的な死因が見えた。V4は敵のいる方向を大きく外している
のではない。**判断時には合っていた方向が、Cloudを往復して届くころには古くなり、
同方向のLONG pulseを重ねて中央を通り過ぎている。**

失敗runの同一target ID 3だけを見ても発生している。

```text
t=4891ms obs18 x=+0.094   すでにFIRE窓付近
t=5032ms obs19 x=-0.225
t=5157ms obs20 x=-0.528
t=5219ms FIRE             obs18から約328ms後

t=5360ms LEFT             xは左側
t=5625ms obs23 x=-0.125
t=5766ms obs24 x=+0.184   中央を通過
t=5938ms LEFT             なお古いLEFTが到着
t=6063ms obs26 x=+0.638   大きく行き過ぎ
```

target IDが切り替わる前からこの現象は起きている。3 laneは新鮮な完全命令を増やす一方、
似た時刻のLEFT判断を複数本抱え、それらが時間差で届くと同方向を再度5 tick保持する。
V4のLONGはCloud空白を埋める主エンジンだったが、敵が近く横移動が速い場面では
「古い方向を再点火する増幅器」に反転する。

したがって次に分離して測るべきなのはtarget lockではなく、次の二つである。

1. token生成時の意味精度: 観測された`x`に対して正しい方向だったか。
2. token実行時の妥当性: 到着時点でも同じ敵が同じ側にいたか。

この二つを混ぜて「LLMのAIMが悪い」と呼ぶと、LLMの空間分類とCloud遅延による時間誤差を
区別できない。GIFが示したのは、後者がかなり大きいということだった。
