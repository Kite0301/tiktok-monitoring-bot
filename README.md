# TikTok モニタリング Bot

GitHub Actions を使って TikTok アカウントの新規投稿を自動検知し、Slack へ通知するボットです。投稿から 24 時間後にパフォーマンス指標（再生数・いいね数など）を再取得して報告します。

## 機能

- **新規投稿検知**: 5 分ごとに登録アカウントをチェックし、新しい投稿を検出したら Slack へ通知
- **24 時間後アナリティクス**: 検出した動画の再生回数・いいね数・コメント数・シェア数・保存数を 24 時間後に収集して Slack へ報告
- **週次レポート**: 毎週月曜日 9:00 JST に稼働状況サマリーを Slack へ送信
- **状態管理**: 既知の動画 ID やアナリティクスジョブを `data/state.json` に保存し、タイムスタンプ等の一時データは GitHub Actions キャッシュで管理

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
│       ├── monitor.yml        # 新規投稿検知ワークフロー（5 分ごと）
│       ├── analytics.yml      # 24h アナリティクスワークフロー（5 分ごと）
│       ├── weekly-report.yml  # 週次レポートワークフロー（毎週月曜 9:00 JST）
│       ├── keepalive.yml      # ワークフロー自動有効化維持
│       └── test-slack.yml     # Slack 通知テスト
├── config/
│   └── accounts.json          # 監視対象アカウント一覧
├── data/
│   └── state.json             # 既知の動画 ID・アナリティクスジョブ（git 管理）
├── src/
│   ├── monitor.py             # 新規投稿検知エントリーポイント
│   ├── analytics.py           # アナリティクス収集エントリーポイント
│   ├── weekly_report.py       # 週次レポートエントリーポイント
│   ├── tiktok_client.py       # yt-dlp ラッパー
│   ├── slack_notifier.py      # Slack 通知クライアント
│   ├── config.py              # 設定読み込み
│   ├── state_manager.py       # 永続状態管理
│   └── cache_manager.py       # 一時状態管理（Actions キャッシュ）
└── requirements.txt
```

## 状態管理の仕組み

このボットは 2 層の状態管理を採用しています。

| 層 | ファイル | 保存場所 | 用途 |
|---|---|---|---|
| 永続状態 | `data/state.json` | git コミット | 既知の動画 ID、アナリティクスジョブ |
| 一時状態 | `data/ephemeral.json` | Actions キャッシュ | 最終確認時刻、連続失敗カウンター |

## Slack 通知の種類

### 新規投稿検知

新しい投稿が見つかった際に送信されます。アカウント名・検出時刻・タイトル・動画リンクを含みます。

### 24 時間後アナリティクス

投稿検知から 24 時間経過後に再生回数・いいね数・コメント数・シェア数・保存数を報告します。

### エラー通知

アカウントが 5 回連続で取得失敗した場合や、アナリティクス収集が最大リトライ回数に達した場合に通知します。

### 週次レポート

毎週月曜日 9:00 JST に、ボットの機能説明と現在の監視アカウント一覧を送信します。

## ローカル実行

```bash
pip install -r requirements.txt

export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

python src/monitor.py
python src/analytics.py
python src/weekly_report.py
```

## ライセンス

MIT
