# V4 side lease — 中央へ着いた古い旋回だけ捨てる

## 発見

V4-Sの18 episodeを肉眼審査すると、`MarineChainsawVzd`は照準よりほんの少し右にいることが多い。
LLMはそこでFIREを返し続け、敵が横移動または接近して当たり判定が照準へ入った時に倒していた。
215 killという高scoreだけでは、この僅かな照準誤差と39.7%の実弾命中率を見落とす。

非同期版には別の失敗もある。CloudがRIGHTを考えている間に同じ敵が中央へ到達し、到着した古い
RIGHT pulseがそのまま照準を敵の向こう側へ運ぶ。そこでlocal側へ照準policyを戻すと「LLMが操作した」
実験ではなくなるため、最小のside leaseだけを置く。

## 最小差分

- LLMが見ていたtarget idと現在のtarget idを比較する。
- visibleな敵を根拠にしたLEFT/RIGHTだけを対象にする。
- 同じ敵がすでに中央のFIRE windowへ入っていたら、その古い方向tokenをWAITへ落とす。
- 敵を見失った、または別targetへ変わった古い方向tokenもWAITへ落とす。
- local側は反対方向もFIREも選ばない。
- 敵が見えない時にLLMが選んだ探索旋回は妨げない。

VAGO同期停止版では推論中に座標が変わらないので、このguardは原理上発火しない。したがって
V4-Sをcontrol、非同期V4をtreatmentとして同じseedで比較できる。

## 「17.8 kill」と今回の敵数

VAGOの公開benchmarkは`defend_the_center`を2100 native tic、約60秒実行し、frame skip 4で
最大525 decision stepと数える。今回のV4-Sはframe skipなしの525 native tic、約15秒である。
双方に`525`が出るが単位が違う。

- VAGO MultiVec: 178 frag / 10 episode = 17.8 frag / 60秒episode
- 今回の修正前V4-S: 215 kill / 18 episode = 11.94 kill / 15秒episode

したがって今回の敵が17体未満で打ち止めになったわけではない。`defend_the_center`は時間中に敵を
追加spawnするため、60秒へ延ばせば遭遇数も増える。scoreの直接比較には入力、action、skill、
frame skip、kill集計方法も揃える必要がある。

## 検証

実装直後のunit testは76件すべて通過した。同じ18 seedをV4-S、その後非同期V4で実測した。

- V4-S: 211 kill、平均11.72、side lease 0 tick
- 非同期: 100 kill、平均5.56、side lease 724 tick / 359 source decision
- 非同期の内訳: FIRE window到達632 tick、target変更52、target消失40

全36本のGIFとseed別状態は[replay index](replays/2026-08-21-v4-side-lease/README.md)へ掲載した。
