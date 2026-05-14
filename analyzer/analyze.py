import os
import time
import sqlite3
import subprocess
import cv2
import threading
import glob
import urllib.request
import urllib.parse
import json
from pathlib import Path
from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer
from ultralytics import YOLO
from datetime import datetime

CAMERA_URLS  = os.environ.get("CAMERA_URLS", "").split(",")
CAMERA_NAMES = os.environ.get("CAMERA_NAMES", "").split(",")
CONFIDENCE   = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.7"))
LAT          = float(os.environ.get("LAT", "35.6"))
LON          = float(os.environ.get("LON", "139.7"))
DB_PATH      = "/data/birds.db"
CLIPS_DIR    = "/data/clips"
PHOTOS_DIR   = "/data/photos"
BUFFER_DIR   = "/data/audio-buffer"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)

con = sqlite3.connect(DB_PATH)
con.execute("""
    CREATE TABLE IF NOT EXISTS detections (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        detected_at     TEXT,
        camera          TEXT,
        common_name     TEXT,
        scientific_name TEXT,
        confidence      REAL,
        clip_file       TEXT,
        photo_file      TEXT,
        gemini_verified INTEGER DEFAULT 0,
        gemini_name     TEXT
    )
""")
for col in ["photo_file", "gemini_verified", "gemini_name"]:
    try:
        if col == "gemini_verified":
            con.execute(f"ALTER TABLE detections ADD COLUMN {col} INTEGER DEFAULT 0")
        else:
            con.execute(f"ALTER TABLE detections ADD COLUMN {col} TEXT")
    except:
        pass
con.commit()
con.close()

bird_analyzer = Analyzer()
yolo = YOLO("yolov8n.pt")
yolo.overrides["verbose"] = False
analyze_lock = threading.Lock()

print("BirdNET Analyzer ready")
print("YOLO bird detector ready")


def verify_with_gemini(common_name: str, scientific_name: str, lat: float, lon: float) -> tuple:
    """
    Geminiに鳥名の検証を依頼。
    返り値: (verified: bool, gemini_name: str or None)
      verified=True  → BirdNETの名前が正しい
      verified=False → Geminiが別の名前を提案
    """
    if not GEMINI_API_KEY:
        return True, None

    prompt = (
        f"BirdNETという鳥声認識AIが、緯度{lat}・経度{lon}（東京近郊）で録音した音声を"
        f"「{common_name}（学名: {scientific_name}）」と識別しました。"
        f"この地域でこの鳥が生息・飛来する可能性はありますか？"
        f"もし明らかに間違いであれば、より可能性の高い鳥の英語名（common name）を1つだけ答えてください。"
        f"正しい可能性が高い場合は「correct」とだけ答えてください。"
        f"余計な説明は不要です。"
    )

    try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        )
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 50, "temperature": 0.1}
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            print(f"  🤖 Gemini: {common_name} → {text}")

            if text.lower() == "correct":
                return True, None
            else:
                return False, text

    except Exception as e:
        print(f"  Gemini APIエラー: {e}")
        return True, None


def get_rtsp_url(camera_name: str) -> str:
    for url, name in zip(CAMERA_URLS, CAMERA_NAMES):
        if name.strip() == camera_name:
            return url.strip()
    return ""


def extract_best_bird_frame(rtsp_url: str) -> tuple:
    if not rtsp_url or "birdmic" in rtsp_url:
        return None, None
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        return None, None
    best_frame, best_conf = None, 0.0
    for i in range(10):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * 45)
        ret, frame = cap.read()
        if not ret:
            continue
        results = yolo(frame, classes=[14], verbose=False)
        for r in results:
            for box in r.boxes:
                conf = float(box.conf[0])
                if conf > best_conf:
                    best_conf  = conf
                    best_frame = frame.copy()
    cap.release()
    if best_frame is not None and best_conf >= 0.4:
        return best_frame, best_conf
    return None, None


def wav_to_mp3(wav_path: str, mp3_path: str) -> bool:
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path,
            "-c:a", "libmp3lame", "-b:a", "64k",
            "-ar", "48000", "-ac", "1",
            mp3_path
        ], capture_output=True, check=True)
        return True
    except Exception as e:
        print(f"  MP3変換エラー: {e}")
        return False


def analyze_segment(wav_path: str, camera_name: str):
    try:
        with analyze_lock:
            recording = Recording(
                bird_analyzer, wav_path,
                lat=LAT, lon=LON,
                min_conf=CONFIDENCE,
            )
            recording.analyze()
            detections = list(recording.detections or [])

        if not detections:
            print(f"  [{camera_name}] 鳥なし")
            return

        rtsp_url   = get_rtsp_url(camera_name)
        photo_file = None
        best_frame, best_conf = extract_best_bird_frame(rtsp_url)
        if best_frame is not None:
            photo_name = f"{camera_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(os.path.join(PHOTOS_DIR, photo_name), best_frame)
            photo_file = photo_name
            print(f"  📸 鳥を撮影 (YOLO {best_conf:.0%})")

        con = sqlite3.connect(DB_PATH)
        for d in detections:
            detected_at    = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            start_sec      = d.get("start_time", 0)
            clip_start     = max(0, start_sec - 5)
            clip_name      = f"{camera_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_t{int(start_sec)}.mp3"
            clip_path      = os.path.join(CLIPS_DIR, clip_name)
            common_name    = d['common_name']
            scientific_name = d['scientific_name']

            # Geminiで鳥名を検証
            verified, gemini_name = verify_with_gemini(
                common_name, scientific_name, LAT, LON
            )
            # Geminiが別の名前を提案した場合はそちらを優先
            display_name = gemini_name if not verified and gemini_name else common_name
            gemini_verified = 1 if verified else 0

            clip_saved = False
            try:
                tmp_wav = clip_path.replace(".mp3", "_tmp.wav")
                subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(clip_start),
                    "-i", wav_path,
                    "-t", "10",
                    "-acodec", "pcm_s16le",
                    "-ar", "48000", "-ac", "1",
                    tmp_wav
                ], capture_output=True, check=True)
                if wav_to_mp3(tmp_wav, clip_path):
                    clip_saved = True
                if os.path.exists(tmp_wav):
                    os.remove(tmp_wav)
            except Exception as e:
                print(f"  クリップ保存エラー: {e}")

            print(f"  🐦 {display_name} ({d['confidence']:.0%}) @ {start_sec}秒"
                  + (" ✓" if verified else f" → Gemini修正: {gemini_name}"))

            con.execute("""
                INSERT INTO detections
                (detected_at, camera, common_name, scientific_name,
                 confidence, clip_file, photo_file, gemini_verified, gemini_name)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (detected_at, camera_name,
                  display_name, scientific_name,
                  d['confidence'],
                  clip_name if clip_saved else None,
                  photo_file,
                  gemini_verified,
                  gemini_name))
        con.commit()
        con.close()

    except Exception as e:
        print(f"  [{camera_name}] 解析エラー: {e}")


def analyze_loop(camera_name: str):
    cam_dir   = os.path.join(BUFFER_DIR, camera_name)
    processed = set()

    print(f"[{camera_name}] 解析ループ開始")

    while not os.path.isdir(cam_dir):
        print(f"[{camera_name}] audio-buffer待機中...")
        time.sleep(5)

    while True:
        try:
            files   = sorted(glob.glob(os.path.join(cam_dir, "*.wav")))
            targets = [f for f in files[:-1] if f not in processed]

            for wav_path in targets:
                print(f"[{camera_name}] 解析: {os.path.basename(wav_path)}")
                analyze_segment(wav_path, camera_name)
                processed.add(wav_path)

            existing  = set(glob.glob(os.path.join(cam_dir, "*.wav")))
            processed &= existing

        except Exception as e:
            print(f"[{camera_name}] ループエラー: {e}")

        time.sleep(5)


for name in CAMERA_NAMES:
    name = name.strip()
    if not name:
        continue
    t = threading.Thread(target=analyze_loop, args=(name,), daemon=True)
    t.start()
    print(f"Started analyzer: {name}")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping...")
