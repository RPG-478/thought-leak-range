# V4-S × VAGO flat-4

## 一言

V4のLLMは六択のまま、LEFT_SHORT / LEFT_LONG / RIGHT_SHORT / RIGHT_LONG / FIRE / WAITを
すべて一判断4 native ticへ畳む。VAGO benchmarkの「一判断をframe skip 4で実行する」身体へ、
V4の頭を載せる実験。

## 条件

- model: `meta-llama/llama-3.1-8b-instruct`
- provider: Groq via OpenRouter、fallbackなし
- scenario: `defend_the_center`
- world: `vago-sync`
- duration: 60 simulation seconds / 2100 native tic
- seed: 7〜16、10 episode
- execution: 3 process並列
- `--vago-frame-skip 4 --vago-flat-pulse`

前のscaled-4はV4の1/2/5 pulseへ4を掛け、LONG=20 ticになって全10本が15秒未満で死亡した。
flat-4はtokenの意味分類を記録したまま、実行長だけを一律4 ticへする。local側は方向もFIREも
選び直さない。

## 結果

| 指標 | flat-4 |
|---|---:|
| kill / hit | 263 / 263 |
| 平均kill | **26.30** |
| 最小 / 最大kill | 22 / 30 |
| 平均生存 | 38.58秒 |
| 最短 / 最長生存 | 32.11 / 43.31秒 |
| 60秒生存 | 0 / 10 |
| LLM判断 | 3,378 |
| 意味正解率 | 76.55% |
| request error | 0 |
| 平均 / p50 latency | 214.2 / 203 ms |
| OpenRouter報告実費 | $0.03427663 |

全seedが22 kill以上、最大30 killになった。scaled-4の平均3.1から約8.5倍であり、
LONG=20 ticがAIM崩壊の主因だったことを強く支持する。

| 条件 | episode設定 | 平均kill | 平均生存 | 完走 |
|---|---:|---:|---:|---:|
| frame skip 1 control（同seed） | 15秒 | 11.9 | 15秒 | 10 / 10 |
| scaled-4（LONG=20） | 60秒 | 3.1 | 12.1秒 | 0 / 10 |
| **flat-4（全action=4）** | 60秒 | **26.3** | **38.6秒** | 0 / 10 |

flat-4はFIRE 1,582、LEFT_LONG 152、LEFT_SHORT 148、RIGHT_LONG 1,197、
RIGHT_SHORT 213、WAIT 5を選んだ。LONG/SHORTの意味判断はログへ残るが、身体はすべて4 tic。
3,378判断からrequest errorは0だった。

VAGO MultiVecの公開値17.8 frag/60秒をraw scoreでは上回ったが、直接対決とは呼ばない。
V4はViZDoom labelsから一体の座標を受け、VAGOはASCII＋depthを入力する。skill、action protocol、
kill集計、学習条件も完全一致していない。ここで確定したのは、**VAGO型flat-4 bodyへ替えると
Cloud LLM V4-SのAIMとscoreが劇的に戻る**ことまでである。

全10 GIFは[replay index](replays/2026-08-21-v4-s-vago-flat-4/README.md)へ掲載した。
