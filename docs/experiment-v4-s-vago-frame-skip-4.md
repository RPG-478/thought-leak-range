# V4-S × VAGO frame skip 4

## 問い

VAGOの公開benchmarkは一回の判断で同じactionを4 native tic保持する。一方、従来V4-Sは
FIREを1 ticだけ進めるため、Cloud判断中に止まった銃のcooldownがほとんど消化されない。
VAGOと同じframe skip 4へするとkillは落ちるのか、逆に実弾が増えて上がるのかを測る。

## 条件

- model: `meta-llama/llama-3.1-8b-instruct`
- provider: Groq via OpenRouter、fallbackなし
- scenario: `defend_the_center`
- world: `vago-sync`
- duration: 60 simulation seconds / 2100 native tic
- seed: 7〜16、10 episode
- execution: 3 process並列
- frame skip: 4

`--vago-frame-skip 4`はmotor pulseの一単位を4 native ticへする。したがってV4のtokenは
FIRE=4、SHORT=8、LONG=20 ticになる。FIREだけを特別扱いせず、VAGO式action holdを
V4の既存pulseへ機械的に掛ける。通常V4-Sと非同期版の既定値は1のまま変更しない。

## 事前予想

- FIRE/cooldown starvationは大きく減る。
- Demonへの実弾は増える。
- Marineへの旋回は粗くなり、LONG 20 ticがovershootを起こし得る。
- killと生存が同時に上がるとは限らない。

## 結果

10本すべて60秒へ届かず、9.4〜14.8秒で死亡した。

| 指標 | 結果 |
|---|---:|
| kill / hit | 31 / 31 |
| 平均kill | 3.10 |
| 最小 / 最大kill | 1 / 5 |
| 60秒生存 | 0 / 10 |
| LLM判断 | 336 |
| 意味正解率 | 90.48% |
| request error | 0 |
| 平均 / p50 latency | 225.8 / 219 ms |
| OpenRouter報告実費 | $0.00394681 |

LLMが選んだtokenはFIRE 92、LEFT_LONG 81、LEFT_SHORT 10、RIGHT_LONG 130、
RIGHT_SHORT 19だった。実行されたlogical pulseは旋回965、FIRE 92で、frame skipを掛けた
native timeの約91%が旋回になった。LONG 211回がそれぞれ20 native ticへ膨らんだ影響が大きい。

一方でFIRE starvationは予想どおり改善した。92 FIRE判断から33発の実弾が出ており、
一判断あたりの発弾率は35.9%。frame skip 1の18 episodeでは4830 FIRE tickから422発、
8.7%だった。銃は約4倍働くようになったが、照準の身体はそれ以上に壊れた。

同じseed 7〜16の15秒・frame skip 1 controlは合計119 kill、平均11.9で全10本が15秒を
走り切っている。今回のskip 4版は同じ15秒へ到達する前に全滅したため、60秒という長い
episodeだけが低scoreの原因ではない。

これはVAGOの4-action policyそのものではない。VAGOは一判断を4 tic保持するが、今回の
V4は既存の1/2/5 pulseへさらに4を掛けたため、SHORT=8、LONG=20になった。次の公平な比較は、
V4のSHORT/LONG区別を一度無効にし、**どのactionも一判断4 ticだけ**に揃えるflat-4である。

全10 GIFは[replay index](replays/2026-08-21-v4-s-vago-frame-skip-4/README.md)へ掲載した。
