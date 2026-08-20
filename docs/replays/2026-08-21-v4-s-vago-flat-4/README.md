# V4-S × VAGO flat-4 — 60秒設定・10 episode

LLMはV4の六択を続けるが、SHORT/LONGを含む全actionを一判断4 native ticへ畳んだ。
seed 7〜16を3 process並列で実行した。

## 結果

- 263 kill / 263 hit、平均26.30 kill
- 最小22 / 最大30 kill
- 平均生存38.58秒、最長43.31秒
- 60秒生存0/10
- 3,378判断、request error 0
- 意味正解率76.55%
- OpenRouter報告実費 $0.03427663

scaled-4ではLONG=20 ticになり平均3.1 killだった。flat-4では全方向を4 ticへ戻しただけで
約8.5倍になった。Cloud判断やworld停止は同じなので、AIM崩壊の主因は長すぎる身体pulseだった。

## GIF

### seed 07〜11

![seed 07](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-07__kills-30__hits-30__health-neg08__seconds-43p3__requests-379__dead.gif)
![seed 08](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-08__kills-25__hits-25__health-neg02__seconds-36p8__requests-322__dead.gif)
![seed 09](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-09__kills-28__hits-28__health-neg10__seconds-42p6__requests-373__dead.gif)
![seed 10](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-10__kills-28__hits-28__health-neg04__seconds-41p0__requests-359__dead.gif)
![seed 11](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-11__kills-26__hits-26__health-00__seconds-36p3__requests-318__dead.gif)

### seed 12〜16

![seed 12](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-12__kills-27__hits-27__health-neg03__seconds-40p1__requests-351__dead.gif)
![seed 13](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-13__kills-24__hits-24__health-neg04__seconds-36p2__requests-317__dead.gif)
![seed 14](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-14__kills-22__hits-22__health-neg04__seconds-35p1__requests-307__dead.gif)
![seed 15](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-15__kills-29__hits-29__health-neg04__seconds-42p4__requests-371__dead.gif)
![seed 16](https://github.com/RPG-478/thought-leak-range/releases/download/replays-v4-s-flat4-2026-08-21/seed-16__kills-24__hits-24__health-neg04__seconds-32p1__requests-281__dead.gif)
