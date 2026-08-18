# Thought Leak Range

> **VizDoomをCloud LLMにやらせた。ゲームを止めず、平均274 msで一発ずつ撃たせる。**

Cloud LLMの判断を、35 Hzで動き続けるoffline ViZDoomへ非同期で接続する実験です。
現在の成功版`direct-bit`では、ViZDoom labelsから作った敵位置をLlama 3.1 8Bへ送り、
visible出力の最初の一文字が厳密な`1`の時だけ、一回のFIRE tickへ直結します。

```text
ViZDoom labels ── OBS#25 ──> Llama 3.1 8B / Groq ──> "1"
       │                                              │
       └─ local body: LEFT / RIGHT only               │
                                                      ▼
                       latest observation + 300 ms freshness guard
                                                      │
                                                      └─ one FIRE tick
```

15秒challengeでは、cloud判断が平均256 ms、観測から実FIRE tickまで平均274 ms。
5発の実弾が5発とも命中し、5体倒したあと画面外のDemonに噛まれて死にました。

![Cloud LLMがViZDoomで5体倒すreplay](docs/assets/episode-5-kills.gif)

| 指標 | 15秒challenge |
|---|---:|
| 受理した判断 | 16 / 16正解 |
| cloud判断latency | 最速204 ms / 中央値265 ms / 平均256 ms |
| 観測 → 実FIRE tick | 平均274 ms |
| ammo / hit / kill | `52 → 47` / 5 / 5 |
| OpenRouter報告実費 | `$0.00012228` |

出発点だった「streamed raw reasoningを盗み見し、final answerもtool callも待たずに
身体へ漏電させる」modeも残っています。`fire-gate`はLLMのraw thinkingを短命な
射撃許可へ変換し、`direct-bit`はthinkingを捨てて本当に一発ずつLLMへ選ばせるbaselineです。

これはオンラインゲームbotではありません。OSのキーボードやマウスには触れず、
同梱のViZDoom練習scenarioだけをAPI経由で操作します。

## 実験の境界

- 敵知覚はraw pixelsでなくViZDoom labelsの構造化位置
- `direct-aim-assist`は左右へ追尾するが、FIREを返せない
- 一発ごとのFIRE / WAITだけはcloud LLMが決め、local側は誤判断を都合よく取消さない
- 推論中もworldは35 Hzで進み、古い判断はlatest-observation / 300 ms guardで捨てる
- raw thought版と一文字classifier版の結果を混ぜない
- commercial game、native input、anti-cheatへ接続しない

## セットアップ

Python 3.12と[uv](https://docs.astral.sh/uv/)を使います。

```powershell
cd prototypes/thought-leak-range
uv sync --extra dev --python 3.12
```

まず課金も通信もない模擬思考で、射撃室と安全装置を確認します。

```powershell
uv run python -m thought_leak_range mock --duration 6
```

OpenRouter版は環境変数を使います。秘密値は引数やrepositoryへ書かないでください。

```powershell
$env:OPENROUTER_API_KEY = Read-Host "OpenRouter API key"
uv run python -m thought_leak_range live `
  --tap-mode thought-phrase `
  --duration 20 `
  --max-requests 8 `
  --max-usd 0.005 `
  --save-thoughts
Remove-Item Env:OPENROUTER_API_KEY
```

既存の`.env`を明示してprocess内だけで読むこともできます。

```powershell
uv run python -m thought_leak_range live `
  --env-file C:\path\outside\repo\.env `
  --tap-mode thought-phrase
```

既定modelはOpenRouter上の正式slug `deepseek/deepseek-v4-flash-0731`、reasoning effortは
このmodelが対応する最小値の`low`です。起動時probeがraw reasoningと有効markerを
確認できなければ、ゲームへ操作権を渡さず停止します。

OpenRouterのproviderは`data_collection=deny`を保ったまま、FPS実験なので
最初のtokenを優先する`sort=latency`を指定します。特定providerを比較する時は
`--provider Groq --no-provider-fallback`のようにfallbackも止めます。

## 三つの思考タップ

| mode | 拾うもの | 扱い |
|---|---|---|
| `marker` | `[[ACT run=...]]` | 既定。nonce付きでfail closed |
| `thought-phrase` | `So action is RIGHT.` | V0。元の発想そのものだが、offline限定 |
| `fire-gate` | `So trigger is ARMED/SAFE.` | LLMは引き金だけ。探索・追従は35 Hzのlocal spine |
| `direct-shot` | raw reasoningのrequest-bound bit | 一判断を一回のFIRE tickへ直結、nonceあり |
| `direct-bit` | visible出力の最初の厳密な`1 / 0` | nonceなし。一文字のstreaming classifier baseline |

DeepSeek V4 Flashは最初の実測で、action markerをraw reasoningではなくvisible回答へ
書きました。そのため安全な`marker` modeは正しく停止しました。
`thought-phrase`はraw reasoning中の狭い決定句を拾う実験用迂回路です。
引用や仮定を完全には判定できないため、オンラインゲームやnative inputには使えません。

動く敵には`fire-gate`を使います。LLMの`ARMED`は発砲そのものではなく3秒の
射撃許可です。local spineが敵を探し、左右へ追従し、敵が中央にいて弾があるtickだけ
発砲します。`SAFE`、期限切れ、敵不在なら即座に撃たなくなります。

```powershell
uv run python -m thought_leak_range live `
  --model deepseek/deepseek-v4-flash-0731 `
  --tap-mode fire-gate `
  --scenario defend_the_center `
  --duration 15 `
  --observation-interval 1.0 `
  --max-requests 10 `
  --max-usd 0.005 `
  --save-thoughts
```

## 2026-08-18の実射

### 固定標的: thinkingを直接WASDへ

最終runではprobeを含む8 requestで、raw reasoningから
`RIGHT`を4回、`FIRE`を1回受理しました。

- 観測からcommit句まで平均1.647秒
- 700 tick中、`RIGHT` 57 tick、`FIRE` 13 tick、dead-man `WAIT` 630 tick
- Cacodemonの画面位置は`+0.450`から`-0.091`へ移動
- 弾薬は`50`から`49`になり、本当に一発出た
- OpenRouter実費は`$0.00045318`

詳しくは[実験記録](docs/experiment.md#raw-reasoning版)へ。

### 動く敵: LLMは引き金だけ

正確な`deepseek/deepseek-v4-flash-0731`と`defend_the_center`で15秒実走し、
左右から来るDemonを4体倒しました。

- probe込み10 request、API error 0
- 有効な`ARMED / SAFE` 6件、平均`1.068秒`、最速`625 ms`
- local spineは探索315 tick、射撃25 tick、射撃許可中169 tick
- ammo `52 → 47`、kill `0 → 4`
- 古い`ARMED`が2件遅着したが、観測世代guardでどちらも棄却
- OpenRouter報告実費`$0.0010724`、上限`$0.005`

`obs=7`の一度の3秒`ARMED` lease中に、脊髄が照準を合わせ続けて2体倒しました。
これは「LLMが一発ずつクリックする」より、遅い判断と速い身体を分業したほうが
FPSらしく動くという最初の実証です。

詳しくは[実験記録](docs/experiment.md#fire-gate版)へ。

### 一発ずつ直接: nonceなしdirect-bit

`Llama 3.1 8B Instruct + Groq`でreasoning、nonce、templateを捨て、visibleの最初の
非空白文字が`1`の時だけ次の一回のFIRE tickへ直結した。

- startup probeは219 ms
- game中16判断を受理、最速204 ms、中央値265 ms、平均255.9 ms
- FIRE / WAITは9 / 7、意味的に16 / 16正解
- 6 FIRE tick、ammo `52 → 47`、5 hit、65 damage、5 kill
- local controllerは左右追尾だけで、中央確認による発砲取消しや再試行なし
- 実費 `$0.00012228`

```powershell
uv run python -m thought_leak_range live `
  --env-file C:\path\outside\repo\.env `
  --model meta-llama/llama-3.1-8b-instruct `
  --provider Groq --no-provider-fallback `
  --tap-mode direct-bit --direct-aim-assist `
  --scenario defend_the_center `
  --duration 15 `
  --direct-max-age-ms 300 `
  --max-tokens 16 --max-requests 40 `
  --max-usd 0.005 --save-thoughts
```

詳しくは[一発ずつ撃つ実験記録](docs/experiment.md#direct-bit版)へ。

## 先行例との差

cloud LLMをViZDoomへ接続した先行例はあります。2026年の
[SauerkrautLM-Doom-MultiVec](https://github.com/VAGOsolutions/SauerkrautLM-Doom-MultiVec)
は、ASCII＋depthからcloud LLMへ4 actionを選ばせています。ただし公開benchmarkは
API completionを同期的に待ってから`make_action()`するため、推論中にworldが進みません。

Thought Leak Rangeは世界初を主張しません。現在の差は、**worldを止めず、非同期cloud判断の
古さを管理し、間に合った一文字だけを一発へする**ことです。比較の詳細は
[先行技術メモ](docs/prior-art.md)へ。

## Roadmap

- `direct-bit`を4操作へ拡張し、LLM自身へ`LEFT / RIGHT / FIRE / WAIT`を任せる
- one-shot actionとfreshness guardを保ったまま、local左右追尾を段階的に外す
- labels版とraw pixels / ASCII / depth版を同じunpaused条件で比較する
- synchronousにworldを止めるbaselineと、35 Hz asynchronous版を同じmodelで比較する
- 複数cloud requestを時間差で走らせ、最新観測だけが身体を取れる三交代制を試す

## 生成物

各runは`runs/<timestamp>/`へ次を残します。

- `events.jsonl`: 観測、marker受信、採用/拒否、action、API metadata
- `summary.json`: latency、request数、token、費用、kill/reward
- `episode.gif`: headlessでも見返せる低fps replay
- `thoughts.jsonl`: `--save-thoughts`を付けた時だけのraw reasoning断片

API keyはどのfileにも保存しません。HTTP errorへkeyが混ざった場合もredactします。

## 安全境界

- markerの文法は `[[ACT run=... obs=... ttl=... action=...]]` のみ
- `direct-bit`はresponseごとにparserを分離し、最初の非空白`1 / 0`以外はfail closed
- actionは`WAIT / LEFT / RIGHT / FIRE`のallow-list
- nonce、観測番号、TTL、重複、最大request数、費用見積りを検査
- `ARMED`だけでは撃たず、最新tickで敵が中央・弾薬ありの時だけlocal spineが発砲
- raw text中の日本語や`FIRE`という単語は実行しない
- leaseが切れたtickは必ず全ボタンを離す
- model出力をshell、Python、任意codeとして実行しない
- commercial game、anti-cheat、native inputへ接続しない

## Test

```powershell
uv run python -m pytest
```
