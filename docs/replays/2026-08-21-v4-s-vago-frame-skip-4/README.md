# V4-S × VAGO frame skip 4 — 60秒設定・10 episode

V4のFIRE=1、SHORT=2、LONG=5 pulseへ、VAGO benchmark型のframe skip 4を機械的に掛けた。
結果はFIRE=4、SHORT=8、LONG=20 native tic。seed 7〜16を3 process並列で実行した。

## 結果

- 31 kill / 31 hit、平均3.10 kill
- 60秒生存0/10
- 全員9.4〜14.8秒で死亡
- request error 0
- FIRE 92判断から33発、発弾率35.9%
- native timeの約91%が左右旋回

frame skipは銃のcooldown starvationを改善した。しかしLONG 20 ticが照準を破壊し、
frame skip 1 controlで全員が生きていた15秒へ一人も到達できなかった。

## GIF

### seed 07〜11

![seed 07](seed-07__kills-02__hits-02__health-00__ticks-354__requests-24__dead.gif)
![seed 08](seed-08__kills-05__hits-05__health-neg02__ticks-456__requests-40__dead.gif)
![seed 09](seed-09__kills-03__hits-03__health-neg07__ticks-434__requests-32__dead.gif)
![seed 10](seed-10__kills-04__hits-04__health-neg01__ticks-518__requests-41__dead.gif)
![seed 11](seed-11__kills-01__hits-01__health-00__ticks-368__requests-37__dead.gif)

### seed 12〜16

![seed 12](seed-12__kills-01__hits-01__health-00__ticks-328__requests-22__dead.gif)
![seed 13](seed-13__kills-05__hits-05__health-neg06__ticks-518__requests-41__dead.gif)
![seed 14](seed-14__kills-05__hits-05__health-neg01__ticks-470__requests-36__dead.gif)
![seed 15](seed-15__kills-04__hits-04__health-neg06__ticks-398__requests-33__dead.gif)
![seed 16](seed-16__kills-01__hits-01__health-00__ticks-386__requests-30__dead.gif)
