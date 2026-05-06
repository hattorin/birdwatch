import sqlite3, os
from flask import Flask, render_template_string, send_file, request

app = Flask(__name__)
DB_PATH    = "/data/birds.db"
CLIPS_DIR  = "/data/clips"
PHOTOS_DIR = "/data/photos"

# 英語名 → 日本語名辞書
BIRD_NAMES_JA = {
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
    "Black Kite": "トビ",
    "Common Pheasant": "キジ",
    "Grey Heron": "アオサギ",
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
    .filter { margin-bottom: 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    select, input, button { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; }
    button { background: #2d6a2d; color: white; cursor: pointer; border: none; }
    table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px;
            overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
    th { background: #2d6a2d; color: white; padding: 10px 12px; text-align: left; }
    td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: middle; }
    tr:hover td { background: #f0fff0; }
    .cam { background: #e8f5e9; border-radius: 4px; padding: 2px 8px; font-size: 0.85em; }
    .conf-high { color: #2d6a2d; font-weight: bold; }
    .conf-mid  { color: #999; }
    audio { height: 28px; max-width: 180px; }
    .bird-photo { width: 120px; height: 80px; object-fit: cover; border-radius: 4px; cursor: pointer; }
    .bird-ja { font-size: 1.05em; font-weight: bold; display: block; }
    .bird-en { font-size: 0.75em; color: #999; display: block; }
    .bird-sci { font-size: 0.72em; color: #bbb; font-style: italic; display: block; }
    .modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%;
             background:rgba(0,0,0,0.8); z-index:100; align-items:center; justify-content:center; }
    .modal.open { display:flex; }
    .modal img { max-width:90vw; max-height:90vh; border-radius:8px; }
    .modal-close { position:fixed; top:20px; right:30px; color:white; font-size:2em; cursor:pointer; }
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
      <button type="submit">絞り込み</button>
    </form>
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
        {% else %}—{% endif %}
      </td>
      <td class="detected-at" data-utc="{{ row[1] }}+00:00"></td>
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
        <audio controls src="/audio/{{ row[6] }}"></audio>
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

  document.querySelectorAll('.detected-at').forEach(el => {
  const val = el.dataset.utc;
  if (!val) return;
  try {
    const d = new Date(val);  // +00:00があるのでUTCと正しく解釈される
    el.textContent = d.toLocaleString(navigator.language, {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  } catch(e) {
    el.textContent = val;
  }
});

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

@app.template_filter('bird_ja')
def bird_ja_filter(name):
    return BIRD_NAMES_JA.get(name, name)

# bird_ja をテンプレートで関数として呼べるようにする
from flask import g
@app.context_processor
def inject_bird_ja():
    return dict(bird_ja=lambda name: BIRD_NAMES_JA.get(name, name))

@app.route("/")
def index():
    sel_cam = request.args.get("cam", "")
    sel_q   = request.args.get("q", "")
    con = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM detections WHERE 1=1"
    params = []
    if sel_cam:
        query += " AND camera=?"; params.append(sel_cam)
    if sel_q:
        query += " AND (common_name LIKE ? OR common_name LIKE ?)"
        # 英語名と日本語名の両方で検索
        ja_to_en = {v: k for k, v in BIRD_NAMES_JA.items()}
        en_query = ja_to_en.get(sel_q, sel_q)
        params.extend([f"%{sel_q}%", f"%{en_query}%"])
    query += " ORDER BY detected_at DESC LIMIT 300"
    rows    = con.execute(query, params).fetchall()
    total   = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    species = con.execute("SELECT COUNT(DISTINCT common_name) FROM detections").fetchone()[0]
    photos  = con.execute("SELECT COUNT(*) FROM detections WHERE photo_file IS NOT NULL").fetchone()[0]
    cameras = [r[0] for r in con.execute("SELECT DISTINCT camera FROM detections").fetchall()]
    con.close()
    return render_template_string(HTML, rows=rows, total=total, species=species,
                                  photos=photos, cameras=cameras,
                                  sel_cam=sel_cam, sel_q=sel_q)

@app.route("/audio/<filename>")
def audio(filename):
    return send_file(os.path.join(CLIPS_DIR, filename), mimetype="audio/wav")

@app.route("/photo/<filename>")
def photo(filename):
    return send_file(os.path.join(PHOTOS_DIR, filename), mimetype="image/jpeg")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
