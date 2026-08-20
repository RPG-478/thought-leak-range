# V3実験記録: 四人制運動野

実験日: 2026-08-19

## 目的

V2 `direct-bit`に残っていたlocal左右追尾を外し、`WAIT / LEFT / RIGHT / FIRE`の全操作を4本のCloud LLM streamへ任せる。推論中もViZDoomは35 Hzで進める。

## 構成

- model: `meta-llama/llama-3.1-8b-instruct`
- provider: OpenRouter経由Groq、fallbackなし
- scenario: `defend_the_center`
- 4専門Agentは各観測で同時に起動
- 各Agentは最初の非空白`1 / 0`だけを返す
- 4票の順序はWAIT / LEFT / RIGHT / FIRE
- 前ラウンド黒板は`o=12 p=0100 e=L`形式
- 裁定優先度は`FIRE >>> WAIT = LEFT = RIGHT`
- FIREは一発消費、旋回は600 ms lease
- FIREは400 ms以内に受理し、35 Hz境界へ載せる50 msの実行猶予
- 8 laneで最大2世代の会議を重ね、古い世代は棄却
- local aim assistなし

## 最終run

artifact: `runs/20260819-011924-1ae69d6f`

| 指標 | 結果 |
|---|---:|
| game ticks | 522（約14.91秒） |
| requests | probe 4 + game 172 |
| game完了 / error | 166 / 2（Groq 429） |
| 受信票 | 166 |
| 意味的正解票 | 156（94.0%） |
| 選択されたラウンド | 25 |
| 選択latency | min 234 / median 265 / mean 273.1 / max 453 ms |
| 世代遅れ棄却 | 44 |
| 期限切れ棄却 | 3 |
| 競合 | 1 |
| tick動作 | WAIT 293 / RIGHT 203 / LEFT 22 / FIRE 4 |
| ammo | 52 → 49 |
| hit / damage / kill | 3 / 35 / 3 |
| 終了health | 0 |
| 実費 | `$0.00085615` |

4回のFIRE tickのうち1回はweapon cooldown中で実弾が出ず、ammoを消費した3発はすべてhitし、3体を倒した。429が2件出てもworldと他streamは止まらなかった。

## 途中run 1: tickへ載る前に消えた弾

artifact: `runs/20260819-011745-f032f62f`

- FIRE Agentがobs 8を297 msで正しく選択
- freshness期限は300 ms
- 次の35 Hz tickまで約28.6 msあるため、実行時には期限切れ
- 0 shot、0 kill、約10秒で死亡

修正として、期限内に受理されたFIREへ50 msのmotor-tick実行猶予を追加した。観測の受理期限そのものは延ばしていない。

## 途中run 2: 4 lane直列会議

artifact: `runs/20260819-011840-bcc5ae6d`

- 4 Agentの一世代が終わるまで次を出さない
- FIRE 1 tick、1 hit、1 kill
- 選択latency平均340.5 ms
- 約11.7秒で死亡

8 laneで二世代をpipeline化すると平均273.1 msへ短縮し、3 killまで増えた。一方で古い44票を捨て、Groq 429も2件出た。速さは無料ではなく、request数と廃棄率へ移った。

## 結論

4つのCloud LLMが、動き続けるViZDoomでlocal操作判断なしに探索・旋回・射撃を完了した。V2の5 killより成績は落ちたが、V2は左右操作がlocalだった。V3の3 killは「全操作がCloud側」という別の達成である。

黒板の配線は完成したが、8Bモデルへ補助判断として読ませると精度が崩れたため、最終runではcontextへ注入しつつ無視するよう指示した。協調記憶としての黒板はV3.1の課題である。
