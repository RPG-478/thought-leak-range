# Public release record — 2026-08-21

Thought Leak Rangeをprivateな実験場からpublic repositoryへ開く時点の記録です。

## 開いたもの

- V0からV4、V4-S、VAGO Async、200 ms latency ablationまでの実装と失敗記録
- seed別の集計JSON、formal benchmark条件、再現command
- Cloud / local spine / stopped world / unpaused worldを区別した比較
- GitHub Releases上のreplay GIFとmanifest
- 実験PC、Cloud provider、Colab T4の再現に必要なsoftware / hardware情報
- MIT license、CI、Dependabot alerts、security policy

## 開かなかったもの

- OpenRouter API key、Colab認証、account、メールアドレス
- hostname、Windows username、端末serial、IP address
- ignored `runs/`内の一時thought、local environment、offline backup bundle
- licenseが明示されていないVAGO upstreamのsource、weights、action policy

「全部公開」は、検証に必要なコード・結果・失敗・環境を隠さないという意味です。第三者が
実験を再現する助けにならず、本人やcredentialだけを識別する情報は含めません。

## 公開前の面白い事故

正式なsecurity scannerは、日本語を含むworkspace pathをCP932で読もうとして
`UnicodeDecodeError`になり、scan開始前に停止しました。そこでtracked treeと到達可能なGit patchを
手動で再検査し、credential-shaped value、個人path、秘密fileがないことを確認しました。

また、VAGO adapterの途中commitにはupstreamのaction fusionを写したprototypeがありました。
最終版はupstream checkoutを動的に呼ぶ薄いadapterへ変更済みですが、公開前に実験branchを最終tree一発の
clean commitへ畳み、licenseが不明な途中実装をpublic historyへ残さない方針にしました。

公開後の匿名HTTP確認でREADMEとRelease GIFはいずれも200を返しました。一方、GitHubはsource branchを
削除しても閉じたPRのread-only refを保持するため、PR #1 / #2から移行前のGIF blobへは到達できます。
そこも追加scanし、秘密値や個人pathは0件でした。映像自体はもともと全公開対象です。通常のbranch / tag graphは
最大blob 122,261 bytesで、普通にcloneする人へ228 MiBを背負わせない目的は維持できています。

## 公開時点の主結果

| 条件 | 平均kill |
|---|---:|
| stopped Cloud V4-S | 26.3 |
| unpaused Cloud V4 | 4.0 |
| unpaused VAGO 1.3M / 28.1 ms | 17.7 |
| same VAGO 1.3M / 200 ms floor | 4.2 |

1.3M専用modelの「賢さ」はそのままに反射神経だけCloud級へ落とすと、戦績までCloudと同じ帯へ落ちた。
この妙な一致が、private実験をpublicな研究の種へ昇格させた理由です。
