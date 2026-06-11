# pli

最終キャッチアップ: 2026-04-29 20:22 (自動生成ひな型)

## ゴール
（要記入。プロジェクトの目的を1〜3行で）

README概要: > **ローカルLLMで動く、完全オフラインの法律通訳AI** > 刑事弁護人のための、依頼者の発言を一切外部に送信しない通訳ツール 開発者: [中野通り法律事務所 弁護士 関 智之](https://github.com/yutoribengoshi) 

## 現在地
（要記入。`/catchup` で自動更新可能）

最終commit: 2026-04-27
"README: 重複した区切り線を削除"

## 直近の決定
（要記入）

## 次やること
- [ ] （要記入）

## 触ったファイル（直近30日）
- README.md
- NOTICE.md
- docs/BENCHMARK.md
- docs/DICTIONARY.md
- ui/attorney_window.py

## メタ情報
- JSONLセッション数（cwd-base）: 96
- /catchup で更新: `/catchup pli`
- Documents配下から触ったセッションは catchup v2 のファイルパス検索でカバー予定

## 関連ノウハウ
（タグ一致した knowhow をここに自動表示）

<!-- CODEX_CATCHUP_START -->
## Codex / Claude Code 引き継ぎ

最終キャッチアップ: 2026-05-22 17:20  
元セッション直近: 2026-04-27

### 現在地
- 実モードで起動完了 ✅ ``` ✅ sounddevice 0.5.5 インストール ✅ Audio devices: 2個（マイク認識OK） ✅ PLI実モード起動 (PID 17711) ``` requirements.txtを更新しておきます（次回環境構築時に同じ問題が起きないように）。
- requirements.txtに `sounddevice` がない。追加してpush。
- push完了 ✅ 軽微な修正（重複`---`）を直しておきます。
- 了解。すぐ非公開に戻します。
- Private化完了 ✅ ``` ══════════════════════════════════════ GitHub Private化 完了 ══════════════════════════════════════ Visibility: PRIVATE Stars/Forks/Watchers: 全て 0（誰にも見られず） 公開時間: 約20分 → タイミング的に第三者の目に触れていない可能性が高い ═══════════...

### 直近の依頼・未了っぽい事項
- ローカルLLmがなんだか弁護士はわからないから説明入れといて
- 公開して良い
- 作成しよう
- 起動してみて
- sttエラーサウンドデバイスが必要と出る

### 触ったファイル
- core/interpreter.py (56回)
- README.md (12回)
- requirements.txt (4回)
- core/nllb_downloader.py (4回)
- docs/MEMORY_OPTIMIZATION.md (3回)
- main.py (3回)
- core/engines/nllb.py (3回)
- data/glossary.json (3回)
- core/opus_downloader.py (2回)
- core/engines/llm.py (2回)
- ui/attorney_window.py (2回)
- ui/stt_control.py (2回)

### 関連セッション
- 2026-05-21 10:32 / 40060d14

### Codex 用メモ
Codex は Claude Code の会話履歴を自動同期しない。このブロックは Claude Code 側の直近ログから生成した引き継ぎである。作業開始時は、案件概要・INDEX・既存書面と照合してから進める。
<!-- CODEX_CATCHUP_END -->
