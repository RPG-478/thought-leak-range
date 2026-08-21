# Thought Leak Range

> **VizDoomをCloud LLMにやらせた。世界を止めず、一文字で探索・旋回・発砲まで選ばせる。**

[![tests](https://github.com/RPG-478/thought-leak-range/actions/workflows/tests.yml/badge.svg)](https://github.com/RPG-478/thought-leak-range/actions/workflows/tests.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Thought Leak Rangeは、Cloud LLMのstreaming出力を35 Hzで動き続けるoffline ViZDoomへ接続する
リアルタイム制御実験です。最初は「LLMのthinkingをそのまま筋肉にしたら面白いのでは？」から始まり、
現在は**actionが何tick古いとFPS agentは壊れるのか**を測る実験装置になっています。

オンラインゲームbotではありません。OSのキーボードやマウス、commercial game、anti-cheatには
接続せず、ViZDoomのローカル練習scenarioだけをAPI経由で操作します。

## 一番面白かった結果

同じseed 7〜16、止まらない35 Hz世界で、VAGOの1.3M専用modelへaction latencyだけを加えました。

| 条件 | 推論中のworld | 観測からactionまで | kill合計 / 平均 |
|---|---|---:|---:|
| Cloud V4-S / Llama 3.1 8B | **停止** | 214.2 msのwall time | **263 / 26.3** |
| Cloud V4 / 同じLLM | 35 Hz継続 | 232.8 ms、約8 tic | **40 / 4.0** |
| VAGO MultiVec 1.3M / T4 | 35 Hz継続 | 28.1 ms、1.049 tic | **177 / 17.7** |
| 同じ1.3M + 200 ms floor | 35 Hz継続 | 7.038 tic | **42 / 4.2** |

1.3M modelは、止まらない世界でも公開値17.8に対して17.7を再現しました。ところがmodel、weights、
入力、action policyを一切変えず、action到着だけを最低200 msへ遅らせると17.7から4.2へ76.3%低下。
Cloud V4の4.0とほぼ同じscore帯へ着地しました。

> **1.3Mの専用脳から賢さを奪わず、反射神経だけCloud並みにしたら、戦績までCloud並みになった。**

これは「両modelの知能が同じ」という意味ではありません。現在の仮説は、リアルタイムAgentの能力を
parameter数や平均推論msだけでなく、**何native tic前の観測を操作しているか**で測るべき、というものです。

- [四条件の詳細](docs/experiment-v4-vago-three-way.md)
- [200 ms latency ablation](docs/experiment-vago-1.3m-200ms-latency.md)
- [論文計画: Action Staleness](docs/paper-plan-action-staleness.md)
- [raw result JSON](docs/results/)

## 動いているところ

V4では、一つの汎用Cloud LLMがWAIT / LEFT / RIGHT / FIREとpulse長を一文字で直接選びます。
このseed 12は5 hit / 5 KILLCOUNT。字幕のMOTOR操作がLLMから届いた一文字です。

![Cloud LLMが一文字でViZDoomを操作して5体倒すreplay](https://github.com/RPG-478/thought-leak-range/releases/download/replays-highlights-2026-08-21/v4-direct-motor-seed12-5-kills.gif)

停止世界のV4-Sでは、同じCloud policyが6体倒します。ただしCloud待機中は敵も時計も止まるため、
これはリアルタイムscoreではなく、System＋LLMの診断上限です。

![停止世界のCloud V4-S](https://github.com/RPG-478/thought-leak-range/releases/download/replays-highlights-2026-08-21/v4-vago-sync-seed12-6-kills.gif)

[全replayとformal / visual-onlyの区別](docs/replays/README.md)も公開しています。GIFはrepository本体を
肥大化させないよう、実験別GitHub Releasesへ置いています。

## 仕組み

### Cloud V4

~~~text
ViZDoom labels: 最接近敵の v / x / ammo
                  │  0.1秒ごと、3 laneを時間差で重ねる
                  ▼
      Llama 3.1 8B via OpenRouter / Groq
                  │  streamed first valid token
                  ▼
   0 WAIT / 1,2 LEFT / 3,4 RIGHT / 5 FIRE
                  │
        文法・観測番号・TTLだけ検査
                  ▼
     35 Hzで止まらないViZDoomへ直接入力
~~~

local側は敵位置から操作を選び直しません。LLMの誤答も、期限と文法を満たせばそのまま実行します。
3 laneは三人格の会議ではなく、同じpolicyを重ねてnetwork待ちを隠す非同期pipelineです。

### VAGO 1.3M adapter

~~~text
screen + depth ──> upstream ASCII/depth converter ──> 1.3M policy on T4
       ▲                                                   │
       │  latest-only observation                          ▼
35 Hz PLAYER thread <── 4-tic composite action <── process boundary
~~~

ViZDoomを専用threadが35 Hzで進め、model processが遅れてもworldを止めません。古い未処理frameは
latest-onlyで置換し、前actionは4 ticで必ず失効します。200 ms実験ではmodel計算後に
「観測時刻＋200 ms」まで待ち、遅い推論のlatencyとthroughputを模擬します。

## 何がLLMで、何がlocalか

| mode | LLMが決めること | local側 |
|---|---|---|
| fire-gate | 数秒のFIRE許可 | 探索、追尾、中央確認、実射 |
| direct-bit | 一発ごとのFIRE / WAIT | 左右追尾 |
| four-agent / V3 | 4 AgentがWAIT / LEFT / RIGHT / FIREへ投票 | 期限付きarbitration |
| direct-motor / V4 | **全操作とpulse長** | 一文字の固定変換と安全検査 |
| VAGO adapter | upstream 1.3M policyのcomposite action | clock、queue、action expiry |

「Cloud LLMがFPSを全部操作した」と呼ぶ主対象はV4です。fire-gateはLLM＋local spineの
階層制御実験であり、LLM自身が照準を合わせた結果とは数えません。

## 再現

### 1. 課金も通信もないmock

Python 3.12と[uv](https://docs.astral.sh/uv/)を使います。

~~~powershell
git clone https://github.com/RPG-478/thought-leak-range.git
cd thought-leak-range
uv sync --extra dev --locked --python 3.12
uv run python -m thought_leak_range mock --duration 6
~~~

### 2. Cloud V4

OpenRouter keyはprocess環境またはignored .envから読みます。repository、引数、ログには書かないでください。

~~~powershell
$env:OPENROUTER_API_KEY = Read-Host "OpenRouter API key"
uv run python -m thought_leak_range live --model meta-llama/llama-3.1-8b-instruct --provider Groq --no-provider-fallback --tap-mode direct-motor --lanes 3 --scenario defend_the_center --duration 15 --observation-interval 0.10 --motor-token-max-age-ms 400 --world-clock clock-thread --motor-body clock-thread --max-tokens 16 --max-requests 180 --max-usd 0.025
Remove-Item Env:OPENROUTER_API_KEY
~~~

model/providerの提供状況と価格は変わり得ます。必ず小さい--max-usdと--max-requestsから始めてください。

### 3. 止まらないVAGO 1.3M

VAGO repositoryとcheckpointは外部入力です。このrepositoryにはweightsもupstream policyも同梱しません。

~~~powershell
uv run python tests/manual_vago_multivec_async_batch.py --upstream C:\path\to\SauerkrautLM-Doom-MultiVec --scenario-path C:\ascii-path\defend_the_center.cfg --device cuda --seeds 7 8 9 10 11 12 13 14 15 16 --output runs\vago-1.3m-async.json
~~~

200 ms floorを再現するには--minimum-action-latency-ms 200を追加します。episodeごとのOS process隔離と
watchdogは、ColabでViZDoomが三episode目に停止した再現性事故を黙って平均から外さないためのものです。

## 実験環境

### このPC

| 項目 | 値 |
|---|---|
| OS | Windows 11 Home 64-bit、10.0.26200 build 26200 |
| CPU | 12th Gen Intel Core i5-1235U、10 cores / 12 logical processors |
| GPU | Intel Iris Xe Graphics、driver 32.0.101.5542、shared integrated memory |
| RAM | 7.7 GiB usable |
| experiment Python | CPython 3.12.10 via uv |
| system Python | CPython 3.14.2（project対象外） |
| uv / Git / PowerShell | uv 0.11.31 / Git 2.52.0.windows.1 / PowerShell 7.6.4 |
| project runtime | httpx 0.28.1 / Pillow 12.3.0 / ViZDoom 1.3.0 |

このPCでVAGO公式同期runnerをCPU再現した時は、Torch CPU推論が平均216.2 msでもworldが停止するため
平均15.6 killでした。GPUを持たないこのPCで独立35 Hz clockとCPU推論を同時に走らせると、model processが
game threadまで飢えさせ14〜20 Hzへ落ちました。したがって正式な止まらない1.3M値はColab T4で取得しています。

### 外部実行環境

| 用途 | 環境 | 主な実測 |
|---|---|---|
| Cloud V4 | OpenRouter、Groq、Llama 3.1 8B Instruct | mean 232.8 ms、平均4.0 kill |
| 1.3M async | Google Colab、Tesla T4、Python 3.12 | compute 28.1 ms、35.019 Hz、平均17.7 kill |
| 1.3M + 200 ms | 同じColab T4 | action age 7.038 tic、35.045 Hz、平均4.2 kill |

公開する環境情報からは、account、メール、端末名、ユーザー名、serial、IP、API key、Colab認証情報を除外しています。

## 公平性と限界

- Cloud V4はViZDoom labelsから最接近敵一体の構造化位置を読む
- VAGOはscreenを40×25 ASCIIへ変換し、16段階depthも読む
- Cloud V4は一文字につき一種類、VAGOは前進・旋回・射撃を同時押しできる
- VAGOは31K human-play framesで学習したDoom専用model、V4は汎用Cloud LLM
- V4-Sの26.3は推論中にworldを止めた診断値で、リアルタイム勝利とは呼ばない
- GIF captureはnative clockを遅くし得るため、formal数値runとvisual-only runを分ける
- KILLCOUNTにはmonster infightingが入り得るため、hit、ammo、damageも併記する
- seed 7〜16の10本は強い予備結果だが、一般化にはseed増量と複数scenarioが必要

このprojectは世界初を主張しません。Cloud LLMをViZDoomへ接続した先行例はあります。差分と、
どこまで反例になるかは[prior artと公平性](docs/prior-art.md)へ明記しています。

## 実験史

| 世代 | 発明と失敗 | 主な結果 |
|---|---|---:|
| V0 | raw reasoning中の自然言語を直接motorへ漏らす | 固定標的へ実射 |
| V2 | LLMは引き金、35 Hz local spineが追尾 | 10 run平均5.4 |
| V3 | WAIT / LEFT / RIGHT / FIREの4 Cloud Agent | 平均1.5、会議が身体を止めた |
| V4 | 一つのLLMが一文字で全操作 | 旧15秒run平均3.5 |
| V4-S | 同じV4で推論中のworldを停止 | flat-4平均26.3 |
| V4 Async | worldとmotorを独立35 Hz clockへ修理 | flat-4平均4.0 |
| VAGO Async | 1.3M専用modelを同じ止まらない世界へ | 平均17.7 |
| VAGO 200 ms | 1.3Mのaction鮮度だけCloud級へ落とす | 平均4.2 |

途中の黒板干渉、敵label取りこぼし、LONG=20 tic、overshoot、CPU starvation、Doom lifecycle hangも
失敗ごと公開しています。[documentation map](docs/README.md)から全記録へ進めます。

## 研究の次

- 30 / 60 / 100 / 150 / 200 / 233 / 300 msのlatency cliffを描く
- 固定delayと同じ平均を持つCloud型jitterを比較する
- stale actionを実行 / 破棄 / 予測補正する条件を比べる
- seed数とscenarioを増やし、bootstrap confidence intervalを出す
- action ageを第一級metricとして、robotics / VLA / networked controlの先行研究を再監査する

詳しくは[paper plan](docs/paper-plan-action-staleness.md)。再現、反証、もっと良い身体、面白い失敗のIssueを歓迎します。

## 生成物と安全境界

runは既定でruns/<timestamp>/へevent、summary、任意のGIF / raw thoughtを保存します。runs/、
.env、virtualenv、build output、GIFはGitから無視されます。

- output tokenはrequest、観測番号、TTLへ束縛し、期限切れ・逆順・重複を拒否
- actionはWAIT / LEFT / RIGHT / FIREのallow-list
- leaseが切れたtickは全ボタンを離す
- model出力をshell、Python、任意codeとして実行しない
- API keyはartifactへ保存せず、HTTP errorでもredact
- live modeはrequest数とUSD budgetを起動前から制限
- native keyboard / mouse inputを実装しない

脆弱性はpublic Issueへ秘密情報を貼らず、[Security policy](SECURITY.md)に従ってprivate advisoryへ報告してください。

## Test

~~~powershell
uv sync --extra dev --locked --python 3.12
uv run python -m pytest -q
~~~

CIはUbuntu / Windows、Python 3.12で実行します。

## Licenseとupstream

Thought Leak Range自身は[MIT License](LICENSE)です。

[VAGOsolutions/SauerkrautLM-Doom-MultiVec](https://github.com/VAGOsolutions/SauerkrautLM-Doom-MultiVec)は
2026-08-21確認時点で明示的なlicense fileがありません。このrepositoryはそのweights、source、action policyを
再配布せず、ユーザーが別途用意したcheckoutを動的に読み込むadapterだけを提供します。upstreamの利用条件は
upstream作者へ確認してください。

---

**くだらないことを、ちゃんと作る。**
