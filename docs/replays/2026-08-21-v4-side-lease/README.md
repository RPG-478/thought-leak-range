# V4 side lease — S control / async 18 episodes

Cloud LLMが選んだLEFT/RIGHTをlocal aimへ置き換えず、同じ敵がすでに中央へ到達した時だけ
古い方向pulseをWAITへ落とす最小overshoot対策を、seed 7〜24で検証した。

## 結果

| 指標 | V4-S control | 非同期side lease |
|---|---:|---:|
| episode | 18 | 18 |
| kill / hit | 211 / 211 | 100 / 100 |
| 平均kill | 11.72 | 5.56 |
| 15秒生存 | 17（seed 18はrequest limit） | 8 |
| LLM判断 | 6,229 | 1,645 |
| 意味正解率 | 76.06% | 87.05% |
| 平均 / p50 token latency | 217.3 / 204 ms | 257.3 / 250 ms |
| stale方向tick棄却 | **0** | **724** |
| OpenRouter報告実費 | $0.06313782 | $0.01744650 |

非同期で棄却した724 tickの内訳は、同じ敵がFIRE windowへ入ったもの632、target変更52、
target消失40だった。pulse中の複数tickを含むため、元になったLLM判断は359件である。
local側は反対方向もFIREも選んでおらず、棄却後はWAITするだけである。

V4-Sでは棄却が完全に0だった。停止世界のLLM＋Systemを変えず、非同期で敵が移動した時だけ
guardが働いたことを示すcontrolになった。seed 18の`464 tick / 5 kill / request limit`も
修正前と完全に再現し、同期世界固有のFIRE/cooldown starvationは都合よく隠していない。

## VAGOの17.8 killより敵が少なく見える理由

VAGOの公開結果は60秒＝2100 native ticをframe skip 4で実行し、最大525 **decision step**と数える。
今回のV4-Sは15秒＝525 **native tic**をframe skipなしで実行する。同じ`525`でもepisode長は4倍違う。
したがって敵が14体程度で枯れたのではなく、今回が4分の1の時間で終わっている。

## V4-S control — 18 GIF

### seed 07〜12

![S seed 07](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-07__kills-11__hits-11__health-82__ticks-525__complete.gif)
![S seed 08](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-08__kills-12__hits-12__health-90__ticks-525__complete.gif)
![S seed 09](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-09__kills-11__hits-11__health-46__ticks-525__complete.gif)
![S seed 10](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-10__kills-10__hits-10__health-80__ticks-525__complete.gif)
![S seed 11](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-11__kills-12__hits-12__health-74__ticks-525__complete.gif)
![S seed 12](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-12__kills-12__hits-12__health-100__ticks-525__complete.gif)

### seed 13〜18

![S seed 13](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-13__kills-13__hits-13__health-84__ticks-525__complete.gif)
![S seed 14](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-14__kills-13__hits-13__health-84__ticks-525__complete.gif)
![S seed 15](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-15__kills-13__hits-13__health-84__ticks-525__complete.gif)
![S seed 16](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-16__kills-12__hits-12__health-100__ticks-525__complete.gif)
![S seed 17](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-17__kills-13__hits-13__health-76__ticks-525__complete.gif)
![S seed 18](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-18__kills-05__hits-05__health-14__ticks-464__request_limit.gif)

### seed 19〜24

![S seed 19](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-19__kills-11__hits-11__health-46__ticks-525__complete.gif)
![S seed 20](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-20__kills-13__hits-13__health-84__ticks-525__complete.gif)
![S seed 21](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-21__kills-14__hits-14__health-84__ticks-525__complete.gif)
![S seed 22](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-22__kills-13__hits-13__health-84__ticks-525__complete.gif)
![S seed 23](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-23__kills-13__hits-13__health-84__ticks-525__complete.gif)
![S seed 24](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-24__kills-10__hits-10__health-24__ticks-525__complete.gif)

## 非同期side lease — 18 GIF

### seed 07〜12

![async seed 07](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-07__kills-05__hits-05__health-00__ticks-414__rejects-21__dead.gif)
![async seed 08](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-08__kills-03__hits-03__health-neg02__ticks-374__rejects-22__dead.gif)
![async seed 09](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-09__kills-05__hits-05__health-neg04__ticks-407__rejects-49__dead.gif)
![async seed 10](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-10__kills-08__hits-08__health-04__ticks-537__rejects-54__survived_15s.gif)
![async seed 11](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-11__kills-08__hits-08__health-10__ticks-537__rejects-62__survived_15s.gif)
![async seed 12](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-12__kills-07__hits-07__health-26__ticks-535__rejects-49__survived_15s.gif)

### seed 13〜18

![async seed 13](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-13__kills-08__hits-08__health-72__ticks-537__rejects-51__survived_15s.gif)
![async seed 14](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-14__kills-07__hits-07__health-44__ticks-531__rejects-58__survived_15s.gif)
![async seed 15](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-15__kills-04__hits-04__health-neg04__ticks-398__rejects-20__dead.gif)
![async seed 16](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-16__kills-03__hits-03__health-neg12__ticks-418__rejects-34__dead.gif)
![async seed 17](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-17__kills-08__hits-08__health-32__ticks-537__rejects-54__survived_15s.gif)
![async seed 18](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-18__kills-04__hits-04__health-neg04__ticks-298__rejects-30__dead.gif)

### seed 19〜24

![async seed 19](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-19__kills-06__hits-06__health-neg08__ticks-512__rejects-40__dead.gif)
![async seed 20](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-20__kills-04__hits-04__health-neg04__ticks-397__rejects-29__dead.gif)
![async seed 21](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-21__kills-06__hits-06__health-38__ticks-538__rejects-47__survived_15s.gif)
![async seed 22](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-22__kills-04__hits-04__health-neg11__ticks-401__rejects-28__dead.gif)
![async seed 23](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-23__kills-02__hits-02__health-neg04__ticks-344__rejects-21__dead.gif)
![async seed 24](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-side-lease-2026-08-21/seed-24__kills-08__hits-08__health-36__ticks-537__rejects-55__survived_15s.gif)
