# TikTok モニタリング Bot

GitHub Actions を使って TikTok アカウントの新規投稿を自動検知し、Slack へ通知するボットです。投稿から 24 時間後にパフォーマンス指標（再生数・いいね数など）を再取得して報告します。

## 機能

- **新規投稿検知**: 登録アカウントを定期的にチェックし、新しい投稿を検出したら Slack へ通知
- **24 時間後アナリティクス**: 検出した動画の再生回数・いいね数・コメント数・シェア数・保存数を 24 時間後に収集して Slack へ報告
- **週次レポート**: 毎週月曜の午前中に稼働状況サマリーを Slack へ送信
- **状態管理**: 既知の動画 ID やアナリティクスジョブを `data/state.json` に保存し、git にコミット

### 実行間隔について

`run.yml` の cron は 5 分ごと (`*/5`) を指定していますが、GitHub Actions のスケジュール実行はベストエフォートで、高頻度の指定ほど間引かれます。**実測では 1 日あたり 14〜17 回（約 1〜1.5 時間間隔）** しか起動しません。週次レポートも「月曜 0:00 UTC」指定に対し、実際の配信は同日の午前中にずれ込みます。

投稿検知が数時間遅れても 24 時間後アナリティクスの精度には影響しないため、現状はこの間隔を許容しています。確実に短い間隔で回したい場合は、外部スケジューラから `workflow_dispatch` を叩く構成が必要です。

## 動作環境

- Python 3.12
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (TikTok データ取得)
- GitHub Actions (定期実行)
- Slack Incoming Webhook (通知)

## セットアップ

### 1. リポジトリの準備

このリポジトリをフォークまたはクローンしてください。

### 2. Slack Incoming Webhook の設定

1. Slack の **App 管理画面** → **Incoming Webhooks** でウェブフックを作成
2. 発行された Webhook URL をコピー

### 3. GitHub Secrets の登録

リポジトリの **Settings → Secrets and variables → Actions** から以下のシークレットを登録します。

| シークレット名 | 説明 |
|---|---|
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook の URL |

### 4. 監視アカウントの設定

`config/accounts.json` に監視したい TikTok アカウントを追加します。

```json
{
  "accounts": [
    "@username1",
    "@username2"
  ]
}
```

> アカウント名は必ず `@` から始めてください。

## ディレクトリ構成

```
.
├── .github/
│   └── workflows/
│       ├── run.yml            # 投稿検知＋アナリティクス収集（定期実行）
│       ├── weekly-report.yml  # 週次レポートワークフロー（毎週月曜）
│       └── test-slack.yml     # Slack 通知テスト（手動実行）
├── config/
│   └── accounts.json          # 監視対象アカウント一覧
├── data/
│   └── state.json             # 既知の動画 ID・アナリティクスジョブ（git 管理）
├── src/
│   ├── run.py                 # エントリーポイント（両フェーズを実行）
│   ├── monitor.py             # 新規投稿検知フェーズ
│   ├── analytics.py           # アナリティクス収集フェーズ
│   ├── weekly_report.py       # 週次レポートエントリーポイント
│   ├── tiktok_client.py       # yt-dlp ラッパー
│   ├── slack_notifier.py      # Slack 通知クライアント
│   ├── config.py              # 設定読み込み
│   ├── state_manager.py       # 状態の読み書き
│   └── git_sync.py            # 状態のコミット＆プッシュ
└── requirements.txt
```

## 実行の流れ

`run.py` が唯一のエントリーポイントで、1 回の実行で次を順に行います。

1. `data/state.json` を読み込む
2. **新規投稿の検知**（`monitor.check_new_posts`）— 新しい投稿を Slack へ通知し、24 時間後のアナリティクスジョブを登録する
3. **アナリティクスの収集**（`analytics.collect_due_analytics`）— 期限が到来したジョブの指標を取得して Slack へ通知する
4. 状態に変化があれば `state.json` を保存し、コミットして push する

2 と 3 は同一プロセス内でひとつの状態オブジェクトを共有します。**`state.json` の書き手が常に 1 つだけ**になるため、両者が互いの変更を git push の競合で失うことがありません。以前は 2 本の独立したワークフローが同じファイルを更新しており、push に失敗した側の変更が失われて同じ動画を再通知する可能性がありました。

どちらかのフェーズが例外で落ちても、もう一方がすでに状態へ書き込んだ内容は保存されます。その場合ワークフローは失敗として終了するので、Actions の画面で気付けます。

## 状態管理の仕組み

状態はすべて `data/state.json` に保存し、内容に変化があったときだけ git へコミットします。

| キー | 用途 |
|---|---|
| `accounts.<username>.known_video_ids` | 通知済みの動画 ID。ここに無い動画を「新規投稿」と判定する |
| `accounts.<username>.consecutive_failures` | 連続取得失敗回数。閾値で頭打ちにする（失敗中のみ存在） |
| `accounts.<username>.failure_notified` | エラー通知済みフラグ。再送を防ぐ（失敗中のみ存在） |
| `pending_analytics` | 24 時間後のアナリティクス取得待ちジョブ |
| `completed_analytics` | 取得済みのアナリティクス履歴（最新 200 件まで保持） |

失敗トラッキング用の 2 キーは、正常時には書き込まれません。復旧するとキーごと削除されるため、健全な状態の `state.json` は投稿データだけを含みます。カウンターを閾値で頭打ちにすることで、障害が続いても state が変化せず、無駄なコミットが発生しません。

初回実行時は、そのアカウントの既存投稿を通知せずに `known_video_ids` へ記録します。

## Slack 通知の種類

### 新規投稿検知

新しい投稿が見つかった際に送信されます。アカウント名・検出時刻・タイトル・動画リンクを含みます。

### 24 時間後アナリティクス

投稿検知から 24 時間経過後に再生回数・いいね数・コメント数・シェア数・保存数を報告します。

### エラー通知

以下の場合に通知します。

- 同一アカウントの投稿取得が **3 回連続で失敗**した場合（アカウントの削除・非公開化、レート制限、yt-dlp の破損など）
- アナリティクス収集が最大リトライ回数（3 回）に達した場合

取得失敗の通知は、障害が続いても**復旧するまで再送しません**。復旧を検知した時点で復旧通知を送り、カウンターをリセットします。

閾値の 3 回は約 4 時間の異常継続に相当します（実行間隔が約 1〜1.5 時間のため）。`src/config.py` の `failure_alert_threshold` で変更できます。

### 週次レポート

毎週月曜の午前中に、ボットの機能説明と現在の監視アカウント一覧を送信します。

## ローカル実行

```bash
pip install -r requirements.txt

export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# 投稿検知とアナリティクス収集（本番と同じ処理）
python src/run.py

# 週次レポート
python src/weekly_report.py
```

> **注意:** `run.py` は状態に変化があると `data/state.json` をコミットして push します。ローカルで試す場合は、意図しないコミットが発生しないよう作業ブランチを切ってから実行してください。

## ライセンス

MIT
