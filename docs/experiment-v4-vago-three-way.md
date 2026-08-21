# 止まるV4、止まらないV4、止まらない1.3M

## 結論

同じseed 7〜16で三条件を比べた。

| 条件 | 頭 | 推論中のworld | 平均推論 | 実効clock | kill合計 / 平均 |
|---|---|---|---:|---:|---:|
| V4-S flat-4 | Cloud Llama 3.1 8B | **停止** | 214.2 ms | 同期 | **263 / 26.3** |
| V4 Async flat-4 | 同じCloud LLM | **35 Hzで進む** | 232.8 ms | 34.41 Hz | **40 / 4.0** |
| VAGO MultiVec 1.3M Async | Colab T4上の専用model | **35 Hzで進む** | **28.1 ms** | **35.019 Hz** | **177 / 17.7** |
| VAGO 1.3M + 200 ms floor | 同じ専用model | **35 Hzで進む** | 200 ms到着 | **35.045 Hz** | **42 / 4.2** |

VAGOの公開値は平均17.8。世界を止めない今回の17.7との差は0.1 killだった。
したがって、1.3M modelの強さは停止世界だけで生じた見せかけではない。実際に速く、
判断がほぼ1 native ticで届くため、世界を進めたままでも成績を維持できる。

逆にCloud V4は、止めれば26.3、止めなければ4.0になる。意味正解率が高くても、約233 ms、
すなわち約8 tic前の旋回・射撃命令はもう古い。**モデルの賢さより、観測から実行までに
世界が何tick進むかが勝敗を決めた。**

## paired seed

| seed | 停止Cloud V4-S | 非同期Cloud V4 | 非同期VAGO 1.3M |
|---:|---:|---:|---:|
| 7 | 30 | 2 | 17 |
| 8 | 25 | 5 | 24 |
| 9 | 28 | 3 | 9 |
| 10 | 28 | 5 | 18 |
| 11 | 26 | 2 | 21 |
| 12 | 27 | 5 | 18 |
| 13 | 24 | 3 | 21 |
| 14 | 22 | 3 | 18 |
| 15 | 29 | 7 | 16 |
| 16 | 24 | 5 | 15 |
| **計 / 平均** | **263 / 26.3** | **40 / 4.0** | **177 / 17.7** |

非同期1.3Mは非同期Cloud V4の4.425倍。停止Cloud V4-Sの67.3%だった。ただし、
停止Cloudの26.3をリアルタイム性能として1.3Mへ勝ったとは扱わない。

## 止まらない1.3Mの条件

- upstream: `VAGOsolutions/SauerkrautLM-Doom-MultiVec`
- model: 同梱`doom-multivec-trained`、約1.3M parameters
- hardware: Google Colab / Tesla T4
- scenario: `defend_the_center`
- seed: 7〜16、10 episode、最大2100 native tic
- ViZDoom `PLAYER`を専用threadが35 Hzで駆動
- 4 ticごとに最新screen＋depthをmodel processへ送信
- action pulseは4 tic。次の判断が遅ければ前actionを延長せずneutralへ戻す
- 観測queueはlatest-only。古い未処理frameは新しいframeで置換
- GIF取得なし

| 指標 | 値 |
|---|---:|
| kill | 177 / 平均17.7 |
| 平均生存 | 46.39秒 |
| 平均実効clock | 35.019 Hz |
| clock valid | 10 / 10 |
| 平均推論 | 28.10 ms |
| 平均action age | 1.049 tic（約30 ms） |
| neutral tic | 166 |
| 観測置換 | 16 |
| episode error | 0 |

実装は[`manual_vago_multivec_async.py`](../tests/manual_vago_multivec_async.py)。
Colabで連続episodeが固まる問題を避けるrunnerは
[`manual_vago_multivec_async_batch.py`](../tests/manual_vago_multivec_async_batch.py)、
全生ログは[`vago-1.3m-async-colab-2026-08-21.json`](results/vago-1.3m-async-colab-2026-08-21.json)。
VAGO側repositoryにはライセンス表記がないため、action policyは複製せず外部agentを動的に呼ぶ。
こちらのCUDA adapterはmodel入出力tensorのdevice移動だけを担当する。

## 面白い事故: 三体目でDoomが黙った

最初は10 episodeを一つのPython processで回した。seed 7は17 kill、seed 8は24 killで正常だったが、
seed 9開始後にViZDoom lifecycleが停止し、6分待っても戻らなかった。そこで各seedを独立OS processへ
隔離し、100秒watchdogとprocess-group killを付けた。残り8本は全て完走した。

これはscore改善ではなく再現性の修理である。固まったepisodeを黙って平均から外さないよう、
batch JSONには失敗seedと出力末尾を必ず残す。

## 公平性の境界

三者は完全な同一policyではない。

- VAGOはscreenをASCIIへ変換しdepthも読む。Cloud V4はViZDoom labelから最近敵一体を読む
- VAGOは前進・旋回・射撃のmulti-hot同時押しを使う。Cloud V4は一文字につき一種類の操作を選ぶ
- VAGOは31K human-play framesで学習したDoom専用model。V4は汎用Cloud LLM
- V4は3本の重複request、VAGOは単一のlatest-only inference worker

よってこれは「どちらのAIが知的か」の直接対決ではない。比較できるのは、止まる／止まらない時計、
推論latency、action age、最終的なsystem挙動である。

## 今回はっきりしたこと

1. VAGO 1.3Mは本当に速くて強い。公開17.8を、止まらない35 Hz世界でも17.7まで再現した。
2. VAGO公開runnerの同期停止は存在するが、高速GPU推論では結果を大きく支えてはいなかった。
3. Cloud V4-Sの26.3は、推論中に世界を止めた診断上限であり、リアルタイムscoreではない。
4. Cloud V4の本当の敵は判断能力だけでなく、約8 ticのstalenessである。
5. **世界停止は遅い脳を強く見せる。速い脳は、そもそも世界を止める必要がない。**

その後の逆実験では、1.3Mを観測からaction到着まで200 msへ人工的に遅らせるだけで、
平均17.7から4.2へ低下した。Cloud V4の4.0とほぼ同じである。詳細は
[VAGO 1.3MをCloudと同じ200 msまで遅くする](experiment-vago-1.3m-200ms-latency.md)。

## この実験が妙に豊作だった理由

ユーザー評は「面白い結果が山ほど」。単一のscore比較から、少なくとも次の枝が同時に生えた。

- 1.3M専用modelは、停止世界の補助輪を外しても公開値をほぼ維持した
- 同じCloud LLMが26.3から4.0へ落ち、stalenessだけを大きく可視化できた
- CPUでは推論processがgame clockまで飢えさせ、GPUでは35 Hzと推論を両立できた
- 一つのPython processでDoomを連続召喚すると三体目で沈黙し、episode隔離が必要になった
- raw killだけなら停止Cloudが最強だが、リアルタイム制御としては1.3Mが明確に勝つという二重の結論になった
- 他者policyのライセンス不明を、コード複製ではなく外部agent adapterへ戻す設計判断につなげた

最初の問いは「1.3Mを止まらないV4へ載せたら？」だけだった。答えを取りに行った結果、
benchmarkの時計、推論機の資源競合、actionの賞味期限、再現runnerの寿命まで一緒に露出した。
一つの数字より、**何を止めると何が強く見えるのか**が実験装置そのものから出てきたのが収穫である。
