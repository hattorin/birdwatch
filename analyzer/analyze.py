import os
import time
import sqlite3
import subprocess
import cv2
import threading
import glob
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
        photo_file      TEXT
    )
""")
try:
    con.execute("ALTER TABLE detections ADD COLUMN photo_file TEXT")
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
            "ffmpeg", "-y",
            "-i", wav_path,
            "-c:a", "libmp3lame",
            "-b:a", "64k",
            "-ar", "48000",
            "-ac", "1",
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
            detected_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            start_sec   = d.get("start_time", 0)
            clip_start  = max(0, start_sec - 5)
            clip_name   = f"{camera_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_t{int(start_sec)}.mp3"
            clip_path   = os.path.join(CLIPS_DIR, clip_name)

            clip_saved = False
            try:
                tmp_wav = clip_path.replace(".mp3", "_tmp.wav")
                subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(clip_start),
                    "-i", wav_path,
                    "-t", "10",
                    "-acodec", "pcm_s16le",
                    "-ar", "48000",
                    "-ac", "1",
                    tmp_wav
                ], capture_output=True, check=True)
                if wav_to_mp3(tmp_wav, clip_path):
                    clip_saved = True
                if os.path.exists(tmp_wav):
                    os.remove(tmp_wav)
            except Exception as e:
                print(f"  クリップ保存エラー: {e}")

            print(f"  🐦 {d['common_name']} ({d['confidence']:.0%}) @ {start_sec}秒")
            con.execute("""
                INSERT INTO detections
                (detected_at, camera, common_name, scientific_name,
                 confidence, clip_file, photo_file)
                VALUES (?,?,?,?,?,?,?)
            """, (detected_at, camera_name,
                  d['common_name'], d['scientific_name'],
                  d['confidence'],
                  clip_name if clip_saved else None,
                  photo_file))
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
