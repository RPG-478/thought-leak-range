# V4-S 18 episodes — Marine認識修正後・overshoot対策前

## このフォルダ

VAGO式にCloud待機中のworldを停止するV4-Sを、seed 7〜24の18 episodeで実行した。
`MarineChainsawVzd`のMonster category / 互換名認識と、一体だけを見るtarget lockは修正済み。
非同期用overshoot対策はまだ入れていない。

ファイル名は次の形式に統一した。

```text
seed-XX__kills-XX__hits-XX__health-XX__ticks-XXX__終了状態.gif
```

17本は15秒＝525 game tickを完走した。seed 18だけは400 requestへ到達し、
464 tickで`request_limit`終了した。この失敗も削除せず掲載する。

## ログ判定: NG — GIF肉眼審査済み

肉眼審査では、Marineは大きく外れているのではなく、照準よりほんの少し右にいることが多かった。
そのままFIREを続け、Marineが横移動または接近して当たり判定が照準へ入った時に倒している。
つまり低い実弾命中率と`RIGHT_SHORT -> FIRE`の大量誤答は、GIFでも同じ現象として確認できた。

高スコアだが、System＋LLMが素直に正しいとは判定できない。

| 指標 | 18 episode合計 |
|---|---:|
| kill / hit | 215 / 215 |
| 平均kill | 11.94 |
| LLM判断 | 5,939 |
| 意味正解率 | 77.56% |
| FIRE game tick | 4,830 |
| 物理的に出た弾 | 422 |
| API error | 1 |
| OpenRouter報告実費 | $0.06025262 |

敵種別ログでは`MarineChainsawVzd`を観測し、少なくとも146 killをFIRE sourceへ
帰属できた。認識修正と実撃破は成功している。一方で次の偏りがある。

| 敵 | FIRE tick | 実弾 | hit | 実弾命中率 |
|---|---:|---:|---:|---:|
| Demon | 417 | 54 | 45 | 83.3% |
| MarineChainsawVzd | 4,413 | 368 | 146 | 39.7% |

Marineでは`RIGHT_SHORT`期待に対して`FIRE`を返した誤りが1,074回あった。
seed 18はFIRE 362回、物理弾26発、5 killのままrequest上限へ達した。
停止世界のスコアが、FIRE連打と銃のcooldown starvationを隠している。

overshoot対策へ進む前に、人間がGIFで次を確認し、2026-08-21に全項目の審査を完了した。

1. Marineが画面中央より右にいるのにFIREを連打しているか。
2. 弾が出ないFIRE中に敵・銃・worldがどう見えるか。
3. seed 18が本当に同じMarineへ固着しているか。
4. seed 11 / 19 / 24の低めのscoreも同じ症状か。

## 一覧

| seed | kill | hit | health | tick | 状態 |
|---:|---:|---:|---:|---:|---|
| 7 | 13 | 13 | 100 | 525 | complete |
| 8 | 12 | 12 | 90 | 525 | complete |
| 9 | 13 | 13 | 100 | 525 | complete |
| 10 | 14 | 14 | 100 | 525 | complete |
| 11 | 10 | 10 | 100 | 525 | complete |
| 12 | 11 | 11 | 80 | 525 | complete |
| 13 | 14 | 14 | 84 | 525 | complete |
| 14 | 13 | 13 | 84 | 525 | complete |
| 15 | 13 | 13 | 84 | 525 | complete |
| 16 | 12 | 12 | 100 | 525 | complete |
| 17 | 12 | 12 | 92 | 525 | complete |
| 18 | 5 | 5 | 14 | 464 | **request_limit** |
| 19 | 9 | 9 | 46 | 525 | complete |
| 20 | 13 | 13 | 84 | 525 | complete |
| 21 | 13 | 13 | 84 | 525 | complete |
| 22 | 14 | 14 | 84 | 525 | complete |
| 23 | 14 | 14 | 72 | 525 | complete |
| 24 | 10 | 10 | 24 | 525 | complete |

## 全episode

### Seed 07 — 13 kill / health 100 / complete

![seed 07](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-07__kills-13__hits-13__health-100__ticks-525__complete.gif)

### Seed 08 — 12 kill / health 90 / complete

![seed 08](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-08__kills-12__hits-12__health-90__ticks-525__complete.gif)

### Seed 09 — 13 kill / health 100 / complete

![seed 09](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-09__kills-13__hits-13__health-100__ticks-525__complete.gif)

### Seed 10 — 14 kill / health 100 / complete

![seed 10](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-10__kills-14__hits-14__health-100__ticks-525__complete.gif)

### Seed 11 — 10 kill / health 100 / complete

![seed 11](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-11__kills-10__hits-10__health-100__ticks-525__complete.gif)

### Seed 12 — 11 kill / health 80 / complete

![seed 12](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-12__kills-11__hits-11__health-80__ticks-525__complete.gif)

### Seed 13 — 14 kill / health 84 / complete

![seed 13](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-13__kills-14__hits-14__health-84__ticks-525__complete.gif)

### Seed 14 — 13 kill / health 84 / complete

![seed 14](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-14__kills-13__hits-13__health-84__ticks-525__complete.gif)

### Seed 15 — 13 kill / health 84 / complete

![seed 15](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-15__kills-13__hits-13__health-84__ticks-525__complete.gif)

### Seed 16 — 12 kill / health 100 / complete

![seed 16](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-16__kills-12__hits-12__health-100__ticks-525__complete.gif)

### Seed 17 — 12 kill / health 92 / complete

![seed 17](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-17__kills-12__hits-12__health-92__ticks-525__complete.gif)

### Seed 18 — 5 kill / health 14 / request limit

![seed 18 request limit](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-18__kills-05__hits-05__health-14__ticks-464__request_limit.gif)

### Seed 19 — 9 kill / health 46 / complete

![seed 19](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-19__kills-09__hits-09__health-46__ticks-525__complete.gif)

### Seed 20 — 13 kill / health 84 / complete

![seed 20](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-20__kills-13__hits-13__health-84__ticks-525__complete.gif)

### Seed 21 — 13 kill / health 84 / complete

![seed 21](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-21__kills-13__hits-13__health-84__ticks-525__complete.gif)

### Seed 22 — 14 kill / health 84 / complete

![seed 22](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-22__kills-14__hits-14__health-84__ticks-525__complete.gif)

### Seed 23 — 14 kill / health 72 / complete

![seed 23](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-23__kills-14__hits-14__health-72__ticks-525__complete.gif)

### Seed 24 — 10 kill / health 24 / complete

![seed 24](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-marine-2026-08-21/seed-24__kills-10__hits-10__health-24__ticks-525__complete.gif)
