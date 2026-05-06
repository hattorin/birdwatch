# 🐦 BirdWatch

Synology NAS上で動作する野鳥検出システム。
RTSPカメラの映像・音声からBirdNET（音声）とYOLOv8（映像）を使って鳥を自動検出・記録します。

## 必要環境
- Synology NAS（Docker対応）
- IPカメラ（RTSP・音声対応）

## セットアップ
1. `.env.example`を`.env`にコピーして設定
2. `docker compose build`
3. `docker compose up -d`
4. `http://NASのIP:5050` でWebUI確認

## データの保存先
- `data/clips/` : 鳥のさえずりクリップ（WAV）
- `data/photos/` : 鳥の写真（JPEG）
- `data/birds.db` : 検出ログ（SQLite）
