# 画像一括加工Webアプリ

Google Mapsから画像を取得し、一括で加工（リサイズ・クロップ・ロゴ合成）できるStreamlitアプリです。

## セットアップ

```bash
# 依存関係のインストール
pip install -r requirements.txt

# Playwright用Chromiumのインストール（必須）
playwright install chromium
```

## 起動方法

```bash
streamlit run app.py
```

## Render へのデプロイ

1. このリポジトリを GitHub にプッシュ
2. [Render](https://render.com) にログイン
3. **New** → **Web Service**
4. リポジトリを接続
5. **Runtime**: Docker を選択
6. **Deploy** をクリック

> **Web上での利用**: GBP取得は **Places API キー必須** です。ローカルアップロードはそのまま利用できます。

## ログイン認証（任意）

環境変数で設定するとログイン画面が表示されます。

- `GBP_APP_USERNAME` … ユーザー名
- `GBP_APP_PASSWORD` … パスワード

**Render**: ダッシュボード → Environment で追加  
**ローカル**: `.env` に記載（`.env.example` を参照）

## 機能

- **GBP取得**: 店舗のGoogle Maps URLを指定して、そのGBPの写真を最大30枚取得
  - **Places API キーあり**: 確実に写真を取得（推奨）
  - **キーなし**: Playwright で取得（枚数が少ない場合あり）
- **ローカルアップロード**: 複数画像をドラッグ＆ドロップ
- **サイズプリセット**: 縦型(1080x1350) / 横型(1024x682)
- **スマートクロップ**: 中心基準のCenter Crop
- **ロゴ合成**: 透過PNGを4隅に配置、オフセット・不透明度調整可能

## Places API キーの取得（推奨）

写真取得が不安定な場合、Google Places API キーを使用すると確実に取得できます。

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. **Places API (New)** を有効化
3. **認証情報** → **API キーを作成**
4. アプリのサイドバー「Google Places API キー」にキーを入力
