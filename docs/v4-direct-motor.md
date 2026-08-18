# V4: 一文字運動野（Direct Motor Token Pipeline）

## 一言

一つのCloud LLMが、方向だけでなく旋回pulseの長さまで一文字で選び、動き続けるViZDoomを直接操作する。

## V3から何を変えるか

V3はWAIT / LEFT / RIGHT / FIREごとに4 requestを送り、各Agentへ自分の出番かを0 / 1で聞いた。全操作はCloud化できたが、10回比較では次が起きた。

- game requestがV2の4.32倍
- 464票を古い世代として棄却
- 身体のWAIT比率60.2%
- 平均kill 1.5。V2は5.4

V4は「4人に聞いてから選ぶ」のをやめ、一つのLLMへ直接一つのmotor tokenを選ばせる。

## Motor token

| token | 操作 | pulse |
|---:|---|---:|
| `0` | WAIT | 1 tick |
| `1` | LEFT_SHORT | 2 ticks |
| `2` | LEFT_LONG | 5 ticks |
| `3` | RIGHT_SHORT | 2 ticks |
| `4` | RIGHT_LONG / SEARCH | 5 ticks |
| `5` | FIRE | 1 tick |

35 Hzなので2 tickは約57 ms、5 tickは約143 ms。pulse長もtokenに含まれるため、local側は敵位置から長短を選ばない。

## 判断用の最初のpolicy

公平な比較と通信系の検証のため、最初は正解が一意になるルールをpromptへ書く。

```text
targetなし                    -> RIGHT_LONG (4)
targetあり、ammoなし          -> WAIT (0)
x < -220                      -> LEFT_LONG (2)
-220 <= x < -80               -> LEFT_SHORT (1)
-80 <= x <= 80                -> FIRE (5)
80 < x <= 220                 -> RIGHT_SHORT (3)
x > 220                       -> RIGHT_LONG (4)
```

`x`は照準中心からの符号付き千分率。LLMはvisible出力の最初の非空白文字として0〜5を一つだけ返す。

## 非同期pipeline

- 0.1秒ごとに最新観測を送る
- 最大3 requestを同時実行する
- Doomは待たず35 Hzで進む
- 新しい観測を送信しただけでは、古い応答を捨てない
- 到着した判断が、最後に採用した観測より新しく、観測から400 ms以内なら採用
- 応答が順不同なら、先に届いた新しい観測番号が勝ち、それより古い後着は棄却
- 新しい有効tokenは実行中の古いpulseを即座に上書きする
- pulseが切れたら全ボタンを離す

V3は「最新観測をcaptureした瞬間」に前世代を無効化したため、推論を終えた大量の票を捨てた。V4は未来のrequestが飛んでいるだけでは現在の新鮮な判断を無効にしない。

## 公平性境界

local側がしてよいこと:

1. ViZDoom labelから`v/x/a`を作る
2. requestと観測番号を結び付ける
3. 一文字をallow-listで読む
4. 年齢・順序を検査する
5. tokenに固定されたpulseをそのまま実行する
6. 正誤とhit/missを後から採点する

local側がしてはいけないこと:

- 敵位置を見てLEFT / RIGHTを選び直す
- FIRE直前に現在の照準を再確認して取消す
- missしそうなFIREをWAITへ変える
- weapon cooldown中のFIREを自動で再試行する
- LLMが選んだ短 / 長pulseを伸縮する

実装には期待動作を計算する採点関数があるが、mock、probe、metricsだけに使う。live motor pathはその結果を参照しない。

## 安全装置

- parserはresponseごとに分離
- 最初の非空白文字以外を探索しない
- 0〜5以外なら永久にfail closed
- 観測番号は単調増加だけ受理
- 最大観測年齢400 ms
- pulseは最大5 tick
- silence、HTTP error、期限切れはWAIT
- native inputやcommercial gameへ接続しない

## 成功条件

1. 6 tokenのstartup probeがすべて正しい
2. local action判断なしで探索・左右旋回・発砲・killを行う
3. V3よりWAIT比率、棄却率、request数を減らす
4. 同じseed 7〜16の10回でV2 / V3と比較する

## 実装・実験結果

4条件すべて達成した。10 runでV4は平均3.5 kill、V3は1.5、V2は5.4。
WAIT比率27.3%、棄却31件、game request 1,072で、V3の60.2%、464件、1,348 requestを
すべて下回った。一方、実弾命中率は45.3%でV2 / V3より低く、長いfew-shot promptのため
費用もV3より高かった。

詳細は[各10回実験](experiment-v4-10x.md)、最初のprobe失敗は
[六択を一行で教えたら三問落とした](v4-probe-language-failure.md)へ分けた。
