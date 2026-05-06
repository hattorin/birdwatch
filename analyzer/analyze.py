import os, time, sqlite3, subprocess, tempfile, cv2, threading
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
SEGMENT_SECS = int(os.environ.get("SEGMENT_SECONDS", "30"))
DB_PATH      = "/data/birds.db"
CLIPS_DIR    = "/data/clips"
PHOTOS_DIR   = "/data/photos"

os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)

# DB初期化
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

# BirdNETはスレッドセーフでないのでロックで直列化
analyze_lock = threading.Lock()

print("BirdNET Analyzer ready")
print("YOLO bird detector ready")


def extract_best_bird_frame(rtsp_url: str):
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


def analyze_segment(rtsp_url: str, camera_name: str):
    print(f"[{camera_name}] Capturing {SEGMENT_SECS}s...")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = tmp.name

    try:
        # 音声30秒取得（明示的にsegment秒数を指定）
        result = subprocess.run([
            "ffmpeg", "-y",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-t", str(SEGMENT_SECS),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "48000",
            "-ac", "1",
            tmp_wav
        ], capture_output=True, timeout=SEGMENT_SECS + 20)

        if result.returncode != 0:
            print(f"  [{camera_name}] FFmpegエラー: {result.stderr[-200:]}")
            return

        # BirdNET解析（ロックで直列化）
        with analyze_lock:
            recording = Recording(
                bird_analyzer, tmp_wav,
                lat=LAT, lon=LON,
                min_conf=CONFIDENCE,
            )
            recording.analyze()
            detections = list(recording.detections or [])

        if not detections:
            print(f"  [{camera_name}] 鳥なし")
            return

        # 鳥検出時のみ写真撮影
        photo_file = None
        best_frame, best_conf = extract_best_bird_frame(rtsp_url)
        if best_frame is not None:
            photo_name = f"{camera_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(os.path.join(PHOTOS_DIR, photo_name), best_frame)
            photo_file = photo_name
            print(f"  📸 鳥を撮影 (YOLO {best_conf:.0%})")

        con = sqlite3.connect(DB_PATH)
        for d in detections:
            detected_at = datetime.now().isoformat(timespec="seconds")
            start_sec   = d.get("start_time", 0)
            clip_start  = max(0, start_sec - 3)
            clip_name   = f"{camera_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_t{int(start_sec)}.wav"
            clip_path   = os.path.join(CLIPS_DIR, clip_name)
            try:
                subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(clip_start),
                    "-i", tmp_wav,
                    "-t", "6",
                    "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
                    clip_path
                ], capture_output=True, check=True)
            except:
                clip_name = None

            print(f"  🐦 {d['common_name']} ({d['confidence']:.0%}) @ {start_sec}秒")
            con.execute("""
                INSERT INTO detections
                (detected_at, camera, common_name, scientific_name,
                 confidence, clip_file, photo_file)
                VALUES (?,?,?,?,?,?,?)
            """, (detected_at, camera_name, d['common_name'], d['scientific_name'],
                  d['confidence'], clip_name, photo_file))
        con.commit()
        con.close()

    except subprocess.TimeoutExpired:
        print(f"  [{camera_name}] タイムアウト")
    except Exception as e:
        print(f"  [{camera_name}] エラー: {e}")
    finally:
        if os.path.exists(tmp_wav):
            os.unlink(tmp_wav)


def camera_loop(rtsp_url: str, camera_name: str):
    print(f"Starting loop: {camera_name}")
    while True:
        try:
            analyze_segment(rtsp_url, camera_name)
        except Exception as e:
            print(f"[{camera_name}] ループエラー: {e}")
            time.sleep(10)


threads = []
for url, name in zip(CAMERA_URLS, CAMERA_NAMES):
    url  = url.strip()
    name = name.strip()
    if url:
        t = threading.Thread(target=camera_loop, args=(url, name), daemon=True)
        t.start()
        threads.append(t)
        print(f"Started: {name}")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Stopping...")
