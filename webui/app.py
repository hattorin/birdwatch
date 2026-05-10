import sqlite3, os, requests, time, threading
from flask import Flask, render_template_string, send_file, request
from datetime import datetime, timedelta

def to_jst(dt_str):
    """UTC文字列をJSTに変換"""
    try:
        dt_str = dt_str.replace('T', ' ')[:19]
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        dt_jst = dt + timedelta(hours=9)
        return dt_jst.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return dt_str

app = Flask(__name__)
DB_PATH    = "/data/birds.db"
CLIPS_DIR  = "/data/clips"
PHOTOS_DIR = "/data/photos"

# 画像URLキャッシュ（/dataボリュームに永続化）
CACHE_PATH = "/data/image_cache.json"
_wiki_cache: dict[str, str] = {}


def _load_cache():
    """起動時にJSONキャッシュをメモリに読み込む"""
    import json
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r") as f:
                _wiki_cache.update(json.load(f))
            print(f"[cache] {len(_wiki_cache)}種 読み込み済み")
        except Exception as e:
            print(f"[cache] 読み込みエラー: {e}")


def _save_cache():
    """キャッシュをJSONに書き出す"""
    import json
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump(_wiki_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[cache] 保存エラー: {e}")

def _fetch_inaturalist(common_name: str) -> str:
    """iNaturalist APIから鳥の代表画像URLを取得"""
    try:
        resp = requests.get(
            "https://api.inaturalist.org/v1/taxa",
            params={"q": common_name, "per_page": 1, "rank": "species"},
            timeout=8,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                url = results[0].get("default_photo", {}).get("medium_url", "")
                if url:
                    return url
        else:
            print(f"[inat] {common_name}: HTTP {resp.status_code}")
    except Exception as e:
        print(f"[inat] {common_name}: {e}")
    return ""


def _fetch_wikipedia(common_name: str) -> str:
    """Wikipedia APIから画像取得（iNaturalistが失敗した場合のフォールバック）"""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "titles": common_name,
                "prop": "pageimages", "pithumbsize": 400, "format": "json",
            },
            headers={"User-Agent": "BirdWatch/1.0"},
            timeout=8,
        )
        if resp.status_code == 200 and resp.text.strip():
            pages = resp.json().get("query", {}).get("pages", {})
            for page in pages.values():
                src = page.get("thumbnail", {}).get("source", "")
                if src:
                    return src
    except Exception as e:
        print(f"[wiki] {common_name}: {e}")
    return ""


def _fetch_one(common_name: str) -> str:
    """iNaturalist → Wikipedia の順でフォールバックしながら画像URL取得"""
    url = _fetch_inaturalist(common_name)
    if not url:
        url = _fetch_wikipedia(common_name)
    return url


def _prefetch_all(names: list):
    """バックグラウンドスレッドで全種を0.5秒間隔で取得"""
    print(f"[inat] プリフェッチ開始: {len(names)}種")
    for name in names:
        if name not in _wiki_cache:
            url = _fetch_one(name)
            _wiki_cache[name] = url
            if url:
                print(f"[inat] OK: {name}")
            time.sleep(0.5)
    _save_cache()
    print("[inat] プリフェッチ完了・キャッシュ保存済み")


def get_wiki_image(common_name: str) -> str:
    """キャッシュから返す。未取得ならその場で1件だけ取得"""
    if common_name in _wiki_cache:
        return _wiki_cache[common_name]
    url = _fetch_one(common_name)
    _wiki_cache[common_name] = url
    return url


BIRD_NAMES_JA = {
    "Warbling White-eye":"メジロ",
    "Common Redshank":"アカアシシギ",
    "Eurasian Coot":"オオバン",
    "Japanese Tit": "シジュウカラ",
    "White's Thrush": "トラツグミ",
    "Ural Owl": "フクロウ",
    "Long-eared Owl": "トラフズク",
    "Rook": "ミヤマガラス",
    "Eurasian Hoopoe": "ヤツガシラ",
    "Eurasian Moorhen": "バン",
    "Oriental Turtle-Dove": "キジバト",
    "Ring-necked Pheasant": "コウライキジ",
    "Brambling": "アトリ",
    "Rock Pigeon": "ドバト",
    "Great Bittern": "サンカノゴイ",
    "Black-crowned Night-Heron": "ゴイサギ",
    "Rose-ringed Parakeet": "ワカケホンセイインコ",
    "Northern Goshawk": "オオタカ",
    "Eurasian Tree Sparrow": "スズメ",
    "Brown-eared Bulbul": "ヒヨドリ",
    "Japanese Bush Warbler": "ウグイス",
    "Japanese White-eye": "メジロ",
    "Great Tit": "シジュウカラ",
    "Carrion Crow": "ハシボソガラス",
    "Large-billed Crow": "ハシブトガラス",
    "Oriental Turtle Dove": "キジバト",
    "Common Kingfisher": "カワセミ",
    "Grey Starling": "ムクドリ",
    "White Wagtail": "ハクセキレイ",
    "Barn Swallow": "ツバメ",
    "Japanese Pygmy Woodpecker": "コゲラ",
    "Great Spotted Woodpecker": "アカゲラ",
    "Black Kite": "トビ",
    "Common Pheasant": "キジ",
    "Grey Heron": "アオサギ",
    "Gray Heron": "アオサギ",
    "Common Cuckoo": "カッコウ",
    "Lesser Cuckoo": "ホトトギス",
    "Osprey": "ミサゴ",
    "Peregrine Falcon": "ハヤブサ",
    "Oriental Greenfinch": "カワラヒワ",
    "Eurasian Jay": "カケス",
    "Azure-winged Magpie": "オナガ",
    "Varied Tit": "ヤマガラ",
    "Long-tailed Tit": "エナガ",
    "Narcissus Flycatcher": "キビタキ",
    "Blue-and-white Flycatcher": "オオルリ",
    "Daurian Redstart": "ジョウビタキ",
    "Dusky Thrush": "ツグミ",
    "Meadow Bunting": "ホオジロ",
    "Eurasian Sparrowhawk": "ハイタカ",
    "Green-winged Teal": "トモエガモ",
}

HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>🐦 BirdWatch</title>
  <style>
    body { font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f8fff8; }
    h1 { color: #2d6a2d; }
    .stats { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
    .stat { background: #e8f5e9; border-radius: 8px; padding: 12px 20px; }
    .stat strong { display: block; font-size: 1.6em; color: #2d6a2d; }
    .filter { margin-bottom: 8px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    select, input, button { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; }
    button { background: #2d6a2d; color: white; cursor: pointer; border: none; }
    table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px;
            overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.1); margin-top: 12px; }
    th { background: #2d6a2d; color: white; padding: 10px 12px; text-align: left; }
    td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: middle; }
    tr:hover td { background: #f0fff0; }
    .cam { background: #e8f5e9; border-radius: 4px; padding: 2px 8px; font-size: 0.85em; }
    .conf-high { color: #2d6a2d; font-weight: bold; }
    .conf-mid  { color: #999; }
    audio { height: 28px; max-width: 180px; }
    .bird-photo { width: 120px; height: 80px; object-fit: cover; border-radius: 4px; cursor: pointer; }
    /* Wikipedia画像はやや薄いボーダーで区別 */
    .bird-photo-wiki { width: 120px; height: 80px; object-fit: cover; border-radius: 4px;
                       cursor: pointer; border: 2px solid #b2dfdb; opacity: 0.92; }
    .wiki-label { font-size: 0.65em; color: #888; display: block; margin-top: 2px; text-align: center; }
    .bird-ja { font-size: 1.05em; font-weight: bold; display: block; }
    .bird-en { font-size: 0.75em; color: #999; display: block; }
    .bird-sci { font-size: 0.72em; color: #bbb; font-style: italic; display: block; }
    .modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%;
             background:rgba(0,0,0,0.8); z-index:100; align-items:center; justify-content:center; }
    .modal.open { display:flex; }
    .modal img { max-width:90vw; max-height:90vh; border-radius:8px; }
    .modal-close { position:fixed; top:20px; right:30px; color:white; font-size:2em; cursor:pointer; }
    .pager { margin-top: 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .pager a { padding: 6px 10px; background: #e8f5e9; border-radius: 4px; text-decoration: none; }
    .pager a.active { background: #2d6a2d; color: white; }
    .pager-info { color: #666; font-size: 13px; }
  </style>
</head>
<body>
  <h1>🐦 BirdWatch 検出ログ</h1>
  <div class="stats">
    <div class="stat"><strong>{{ total }}</strong>総検出数</div>
    <div class="stat"><strong>{{ species }}</strong>種類</div>
    <div class="stat"><strong>{{ photos }}</strong>写真あり</div>
  </div>

  <div class="filter">
    <form method="get">
      カメラ:
      <select name="cam" onchange="this.form.submit()">
        <option value="">全て</option>
        {% for c in cameras %}
        <option value="{{ c }}" {% if c == sel_cam %}selected{% endif %}>{{ c }}</option>
        {% endfor %}
      </select>
      鳥名:
      <input type="text" name="q" value="{{ sel_q }}" placeholder="例: インコ">
      表示件数:
      <select name="per_page" onchange="this.form.submit()">
        {% for n in [20, 50, 100, 200] %}
        <option value="{{ n }}" {% if n == per_page %}selected{% endif %}>{{ n }}件</option>
        {% endfor %}
      </select>
      重複抑止:
      <select name="dedup_min" onchange="this.form.submit()">
        {% for m in [0, 1, 5, 10, 30, 60] %}
        <option value="{{ m }}" {% if m == dedup_min %}selected{% endif %}>
          {% if m == 0 %}なし{% else %}{{ m }}分以内{% endif %}
        </option>
        {% endfor %}
      </select>
      <button type="submit">絞り込み</button>
    </form>
  </div>

  <div class="pager">
    <span class="pager-info">{{ total_count }}件中 {{ (page-1)*per_page+1 }}〜{{ [page*per_page, total_count]|min }}件表示</span>
    <div style="margin-left:auto; display:flex; gap:4px;">
      {% if page > 1 %}
      <a href="?page=1&per_page={{ per_page }}&cam={{ sel_cam }}&q={{ sel_q }}&dedup_min={{ dedup_min }}">«</a>
      <a href="?page={{ page-1 }}&per_page={{ per_page }}&cam={{ sel_cam }}&q={{ sel_q }}&dedup_min={{ dedup_min }}">‹ 前へ</a>
      {% endif %}
      {% for p in range([1, page-2]|max, [total_pages+1, page+3]|min) %}
      <a href="?page={{ p }}&per_page={{ per_page }}&cam={{ sel_cam }}&q={{ sel_q }}&dedup_min={{ dedup_min }}"
         class="{{ 'active' if p == page else '' }}">{{ p }}</a>
      {% endfor %}
      {% if page < total_pages %}
      <a href="?page={{ page+1 }}&per_page={{ per_page }}&cam={{ sel_cam }}&q={{ sel_q }}&dedup_min={{ dedup_min }}">次へ ›</a>
      <a href="?page={{ total_pages }}&per_page={{ per_page }}&cam={{ sel_cam }}&q={{ sel_q }}&dedup_min={{ dedup_min }}">»</a>
      {% endif %}
    </div>
  </div>

  <table>
    <tr>
      <th>写真</th><th>日時</th><th>カメラ</th><th>鳥の名前</th><th>信頼度</th><th>音声</th>
    </tr>
    {% for row in rows %}
    <tr>
      <td>
        {% if row[7] %}
          <img class="bird-photo" src="/photo/{{ row[7] }}"
               onclick="openModal('/photo/{{ row[7] }}')" alt="bird">
        {% elif wiki_images.get(row[3]) %}
          <img class="bird-photo-wiki"
               src="{{ wiki_images[row[3]] }}"
               onclick="openModal('{{ wiki_images[row[3]] }}')"
               alt="{{ row[3] }}"
               onerror="this.parentElement.innerHTML='—'">
          <span class="wiki-label">© iNaturalist</span>
        {% else %}
          —
        {% endif %}
      </td>
      <td>{{ to_jst(row[1]) }}</td>
      <td><span class="cam">{{ row[2] }}</span></td>
      <td>
        <span class="bird-ja">{{ bird_ja(row[3]) }}</span>
        <span class="bird-en">{{ row[3] }}</span>
        <span class="bird-sci">{{ row[4] }}</span>
      </td>
      <td class="{{ 'conf-high' if row[5] >= 0.8 else 'conf-mid' }}">
        {% if row[5] > 0 %}{{ "%.0f"|format(row[5]*100) }}%{% else %}—{% endif %}
      </td>
      <td>
        {% if row[6] %}
        <audio controls>
          <source src="/audio/{{ row[6] }}"
                  type="{{ 'audio/mpeg' if row[6].endswith('.mp3') else 'audio/wav' }}">
        </audio>
        {% else %}—{% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>

  <div class="modal" id="modal" onclick="closeModal()">
    <span class="modal-close">✕</span>
    <img id="modal-img" src="">
  </div>

  <script>
    function openModal(src) {
      document.getElementById('modal-img').src = src;
      document.getElementById('modal').classList.add('open');
    }
    function closeModal() {
      document.getElementById('modal').classList.remove('open');
    }
  </script>
</body>
</html>
"""

@app.context_processor
def inject_bird_ja():
    return dict(
        bird_ja=lambda name: BIRD_NAMES_JA.get(name, name),
        to_jst=to_jst
    )


@app.route("/")
def index():
    sel_cam   = request.args.get("cam", "")
    sel_q     = request.args.get("q", "")
    page      = int(request.args.get("page", 1))
    per_page  = int(request.args.get("per_page", 50))
    dedup_min = int(request.args.get("dedup_min", 5))
    dedup_secs = dedup_min * 60

    con = sqlite3.connect(DB_PATH)

    base_query = """
        SELECT d.*
        FROM detections d
        WHERE NOT EXISTS (
            SELECT 1 FROM detections d2
            WHERE d2.common_name = d.common_name
            AND ABS(
                strftime('%s', replace(d.detected_at,  'T', ' ')) -
                strftime('%s', replace(d2.detected_at, 'T', ' '))
            ) < ?
            AND (
                (d2.camera = 'verander_mic' AND d.camera != 'verander_mic')
                OR (
                    (d2.camera = 'verander_mic') = (d.camera = 'verander_mic')
                    AND d2.id < d.id
                )
            )
        )
    """

    params = [dedup_secs]

    if sel_cam:
        base_query += " AND d.camera=?"
        params.append(sel_cam)
    if sel_q:
        base_query += " AND (d.common_name LIKE ? OR d.common_name LIKE ?)"
        ja_to_en = {v: k for k, v in BIRD_NAMES_JA.items()}
        en_query = ja_to_en.get(sel_q, sel_q)
        params.extend([f"%{sel_q}%", f"%{en_query}%"])

    total_count = con.execute(
        f"SELECT COUNT(*) FROM ({base_query})", params
    ).fetchone()[0]

    query = base_query + " ORDER BY replace(d.detected_at,'T',' ') DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    rows    = con.execute(query, params).fetchall()
    total   = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    species = con.execute("SELECT COUNT(DISTINCT common_name) FROM detections").fetchone()[0]
    photos  = con.execute("SELECT COUNT(*) FROM detections WHERE photo_file IS NOT NULL").fetchone()[0]
    cameras = [r[0] for r in con.execute("SELECT DISTINCT camera FROM detections").fetchall()]
    con.close()

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    # キャッシュから画像URLを引くだけ（取得はバックグラウンドで完了済み）
    wiki_images = {row[3]: _wiki_cache.get(row[3], "") for row in rows if not row[7]}

    return render_template_string(HTML, rows=rows, total=total, species=species,
                                  photos=photos, cameras=cameras,
                                  sel_cam=sel_cam, sel_q=sel_q,
                                  page=page, per_page=per_page,
                                  total_pages=total_pages,
                                  total_count=total_count,
                                  dedup_min=dedup_min,
                                  wiki_images=wiki_images)


@app.route("/audio/<filename>")
def audio(filename):
    mp3_path = os.path.join(CLIPS_DIR, filename)
    wav_path = mp3_path.replace(".mp3", ".wav")
    if os.path.exists(mp3_path):
        return send_file(mp3_path, mimetype="audio/mpeg")
    elif os.path.exists(wav_path):
        return send_file(wav_path, mimetype="audio/wav")
    return "Not found", 404


@app.route("/photo/<filename>")
def photo(filename):
    return send_file(os.path.join(PHOTOS_DIR, filename), mimetype="image/jpeg")


if __name__ == "__main__":
    # 起動時にキャッシュ読み込み → 未取得分だけプリフェッチ
    _load_cache()
    all_names = list(BIRD_NAMES_JA.keys())
    t = threading.Thread(target=_prefetch_all, args=(all_names,), daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5050, debug=False)
