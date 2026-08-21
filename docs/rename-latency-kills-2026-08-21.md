# Thought Leak Range → Latency Kills

2026-08-21、projectとGitHub repositoryの表示名を`Latency Kills`へ変更した。

## なぜ

`Thought Leak Range`は、LLMのstreaming reasoningを最終回答より先に拾い、射撃へ漏らしたV0には
正確な名前だった。その後projectの中心は、Cloud LLMと1.3M専用modelのaction age、停止世界、
35 Hz clock、200 ms latency ablationへ移った。

`Latency Kills`には二つの意味がある。

1. 古いactionがreal-time agentの戦績を殺す。
2. FPSなので、文字どおりkillを数えている。

## 変えたもの

- GitHub repository: `RPG-478/thought-leak-range` → `RPG-478/latency-kills`
- README title、badge、clone URL、Release asset URL
- repository descriptionとOpenRouter `X-Title`
- 現在のprojectを指す文書上の表示名

## 残したもの

- Python distribution / CLI: `thought-leak-range`
- Python module: `thought_leak_range`
- V0の技術名としての`Thought Leak`
- 過去の実験世代V2 / V3 / V4 / V4-S

packageまで同時にrenameすると既存の再現commandとimportを壊すため、repository/display renameと
runtime compatibilityを分けた。Windowsの日本語workspaceで新しいconsole launcherを試した際にも、
module実行は成功した一方launcherが`Access denied`になったため、無理に広げず撤回した。

## 名前が結果を説明する

同じVAGO 1.3M policyは約28 msで平均17.7 kill、action到着だけを200 msへ遅らせると平均4.2 kill。
新しい看板は、このprojectが今測っているものを旧名より短く説明する。
