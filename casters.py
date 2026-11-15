"""キャスター(顔・口・目の画像)と声(VOICEVOX)の組み合わせを、日付で4人ローテーションする部品。
  c0 = 今までのキャスター(青山龍星) / c1 = 男性(雀松朱司) / c2 = 白い服の女性(後鬼 鬼ver) / c3 = 黒いスーツの女性(WhiteCUL たのしい)
  選ぶ日付 = 動画の日付(レースの日)。日付から自動で決まり、横動画・ショート・サムネは同じ日なら同じ人。
  声が見つからないときは、その日だけ c0(今までのキャスター・青山龍星)に自動で戻す。
"""
import datetime
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
FILES = ["caster_base.png", "mouth_closed.png", "mouth_a.png", "mouth_i.png", "mouth_u.png",
         "mouth_e.png", "mouth_o.png", "eyes_closed.png"]

CASTERS = [
    {"id": "c0", "dir": None, "voice": "青山龍星", "styles": ["ノーマル"], "any_style": True, "credit": "青山龍星"},
    {"id": "c1", "dir": "casters/c1", "voice": "雀松朱司", "styles": ["ノーマル"], "any_style": True, "credit": "雀松朱司"},
    {"id": "c2", "dir": "casters/c2", "voice": "後鬼", "styles": ["鬼ver.", "鬼ver"], "style_contains": "鬼",
     "any_style": False, "credit": "後鬼"},
    {"id": "c3", "dir": "casters/c3", "voice": "WhiteCUL", "styles": ["たのしい"], "any_style": False, "credit": "WhiteCUL"},
]


def pick_for_date(date):
    """date = '20261114' など。通算日数を4で割った余りで、4人が順番に回る"""
    forced = os.environ.get("CASTER_FORCE", "").strip()      # テスト用: 例 CASTER_FORCE=c2 で、その人に固定する
    if forced:
        for c in CASTERS:
            if c["id"] == forced:
                return c
        raise SystemExit(f"CASTER_FORCE={forced} は存在しません(c0〜c3)")
    if not date:
        return CASTERS[0]
    d = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:8]))
    return CASTERS[d.toordinal() % len(CASTERS)]


def by_id(cid):
    for c in CASTERS:
        if c["id"] == cid:
            return c
    return CASTERS[0]


def find_style_id(speakers, caster):
    """VOICEVOXの /speakers の一覧から、声の名前+スタイルで番号を探す。見つからなければ None"""
    for s in speakers:
        if s.get("name") != caster["voice"]:
            continue
        for want in caster["styles"]:
            for st in s["styles"]:
                if st["name"] == want:
                    return st["id"]
        key = caster.get("style_contains")
        if key:
            for st in s["styles"]:
                if key in st["name"]:
                    return st["id"]
        if caster.get("any_style") and s["styles"]:
            return s["styles"][0]["id"]
    return None


def asset_dir(caster):
    return ASSETS if not caster["dir"] else os.path.join(ASSETS, caster["dir"])


def caster_json(caster):
    with open(os.path.join(asset_dir(caster), "caster.json"), encoding="utf-8") as f:
        return json.load(f)


def apply_assets(caster, out_assets):
    """動画づくりの作業場(out/assets)に、選ばれたキャスターの画像を上書きでコピーする"""
    if not caster["dir"]:
        return
    src = asset_dir(caster)
    for fn in FILES:
        shutil.copyfile(os.path.join(src, fn), os.path.join(out_assets, fn))


def write_used(out, caster, date):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "caster_used.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date, "id": caster["id"], "voice": caster["voice"]}, f, ensure_ascii=False)


def read_used(out, date):
    """同じ日の動画づくりで使ったキャスター。なければ None"""
    try:
        with open(os.path.join(out, "caster_used.json"), encoding="utf-8") as f:
            d = json.load(f)
        if d.get("date") == date:
            return by_id(d.get("id"))
    except Exception:
        pass
    return None
