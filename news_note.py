# -*- coding: utf-8 -*-
"""
news_note.py ― noteに貼る「全レース買い目」(直前情報を読み込む前・1コース先マイ・5つの帯)の画像と文面を作り、メールで送る。

・買い目は、出走表サイトと同じ計算(非公開側の news_picks.py。画面 boat_scenario_pro.html をそのまま動かす)で出す。
・出走表は、非公開側に保存された data/race_card_latest.json を使う。公式サイトには、アクセスしない。
・今日の出走表でないとき(日付が違うとき)は、古い買い目を送らず、失敗で終える。
・計算できなかったレースは、間違った数字を出さず、画像に「計算できませんでした」と出す。
・画像は、1場を6レースずつ(1〜6R・7〜12R)の縦長。ZIPにまとめて、メールに添付する(noteに、まとめてドラッグできる)。
・メールは、Xのメールと同じ仕組み(Gmail・アプリパスワード)。同じ日の二重送信は、uploaded/日付_note_mail.json で防ぐ。

環境変数: MAIL_USER, MAIL_TO, GMAIL_APP_PASSWORD
使い方: python news_note.py --bsp bsp --out note_out [--force] [--no-mail]
"""
import argparse
import glob
import json
import os
import smtplib
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from PIL import Image, ImageDraw, ImageFont

JST = timezone(timedelta(hours=9))

VENUE_CODE = {"桐生": "01", "戸田": "02", "江戸川": "03", "平和島": "04", "多摩川": "05", "浜名湖": "06",
              "蒲郡": "07", "常滑": "08", "津": "09", "三国": "10", "びわこ": "11", "住之江": "12",
              "尼崎": "13", "鳴門": "14", "丸亀": "15", "児島": "16", "宮島": "17", "徳山": "18",
              "下関": "19", "若松": "20", "芦屋": "21", "福岡": "22", "唐津": "23", "大村": "24"}
NAME = {v: k for k, v in VENUE_CODE.items()}

# 帯の並びと名前(news_picks.py と同じ。非公開側の news_picks.py が読めるときは、そちらを使う)
BANDS = ["prob", "bal", "ev", "hm", "ml"]
LABELS = {"prob": ("確率(高)", "確率1〜8位"), "bal": ("確率(中)", "確率7〜18位"), "ev": ("確率(低)", "確率17〜36位"),
          "hm": ("確率(高)〜(中)", "確率1〜18位"), "ml": ("確率(中)〜(低)", "確率19〜36位")}

# 艇の色(出走表サイトと同じ): 1白 2黒 3赤 4青 5黄 6緑 → (背景, 文字, 枠)
BOAT = {1: ("#ffffff", "#111111", "#8a8a8a"), 2: ("#111111", "#ffffff", None), 3: ("#d62828", "#ffffff", None),
        4: ("#1d6fd1", "#ffffff", None), 5: ("#f4d81c", "#111111", None), 6: ("#1e9e3a", "#ffffff", None)}

# 画像の寸法(note の本文では、幅620px前後に縮小して表示される。その2倍で作って、拡大しても読める細かさにする)
W = 1200
MARGIN = 32
LABEL_W = 232
CELL = 38
DASH = 10
CHIP_GAP = 14
CHIP_W = CELL * 3 + DASH * 2
LINE_H = CELL + 10
PER_IMAGE = 6          # 1枚に入れるレース数(標準。--per-image で変えられる)

TEMPLATE = (
    "前日に、解析ツール BOAT REX PRO を使用し、攻め筋を1コース先マイを選択した際の買い目です。\n"
    "ボートレース(競艇)専門誌 BOAT REX PRO(https://boat-rex-pro.com/)では、\n"
    "直前情報を読み込んだ上での買い目を掲載しています。\n"
    "また、ボートレース(競艇)専門誌 BOAT REX PROでは、買い目だけでなく、\n"
    "予想に役立つオリジナル出走表を掲載しています。ぜひご活用ください。"
)


def log(s):
    print(s, flush=True)


def find_font(bold=True):
    names = ["NotoSansCJK-Bold.ttc", "NotoSansCJK-Medium.ttc", "NotoSansCJK-Regular.ttc"] if bold else \
            ["NotoSansCJK-Regular.ttc", "NotoSansCJK-Medium.ttc"]
    for n in names:
        for p in glob.glob(f"/usr/share/fonts/**/{n}", recursive=True):
            return p
    for p in glob.glob("/usr/share/fonts/**/*CJK*", recursive=True) + glob.glob("/usr/share/fonts/**/*Gothic*", recursive=True):
        return p
    raise RuntimeError("日本語のフォント(fonts-noto-cjk)が見つかりません")


class Fonts:
    def __init__(self):
        self.bold_path = find_font(True)
        self.reg_path = find_font(False)
        self._c = {}

    def get(self, size, bold=True):
        k = (size, bold)
        if k not in self._c:
            self._c[k] = ImageFont.truetype(self.bold_path if bold else self.reg_path, size)
        return self._c[k]


def text_w(d, s, font):
    return d.textlength(s, font=font)


def draw_chip(d, x, y, key, fonts):
    """3つの艇番を、色つきの四角で並べる(例 1-4-3)。幅 CHIP_W"""
    nums = [int(n) for n in key.split("-")]
    f = fonts.get(28, True)
    for i, n in enumerate(nums):
        cx = x + i * (CELL + DASH)
        bg, fg, bd = BOAT[n]
        d.rounded_rectangle([cx, y, cx + CELL - 1, y + CELL - 1], radius=7, fill=bg, outline=bd, width=2 if bd else 0)
        tw = text_w(d, str(n), f)
        d.text((cx + (CELL - tw) / 2, y + CELL / 2), str(n), font=f, fill=fg, anchor="lm")
        if i < 2:
            d.rectangle([cx + CELL + 1, y + CELL // 2 - 1, cx + CELL + DASH - 2, y + CELL // 2 + 1], fill="#8a94a3")


def chips_per_line():
    area = W - MARGIN * 2 - LABEL_W
    return max(1, int((area + CHIP_GAP) // (CHIP_W + CHIP_GAP)))


def band_lines(n):
    per = chips_per_line()
    return max(1, -(-n // per))


def race_height(pk):
    h = 56 + 14
    if pk and pk.get("ok"):
        for b in BANDS:
            h += band_lines(len(pk["bands"][b])) * LINE_H + 22
    else:
        h += 80
    return h + 22


def render_image(path, date, venue, race_nos, picks, fonts):
    """picks: {race_no: {ok, bands:{帯:[{key,prob}|key]}}}"""
    HEAD, FOOT = 168, 96
    total = HEAD + sum(race_height(picks.get(n)) for n in race_nos) + FOOT
    img = Image.new("RGB", (W, total), "#ffffff")
    d = ImageDraw.Draw(img)
    # 上の帯
    d.rectangle([0, 0, W, HEAD], fill="#0f2742")
    d.text((MARGIN, 40), "解析ツール BOAT REX PRO", font=fonts.get(32), fill="#ffd54a", anchor="lm")
    a, b = race_nos[0], race_nos[-1]
    rng = f"{a}R" if a == b else f"{a}〜{b}R"
    d.text((MARGIN, 94), f"{date.month}月{date.day}日 {venue} {rng} の買い目", font=fonts.get(52), fill="#ffffff", anchor="lm")
    d.text((MARGIN, 144), "直前情報を読み込む前 ・ 攻め筋は1コース先マイ", font=fonts.get(26, False), fill="#c9d6e8", anchor="lm")
    y = HEAD + 8
    per = chips_per_line()
    for n in race_nos:
        pk = picks.get(n)
        d.rectangle([MARGIN, y, W - MARGIN, y + 56], fill="#1f3a5f")
        d.text((MARGIN + 18, y + 28), f"{venue} {n}R", font=fonts.get(34), fill="#ffffff", anchor="lm")
        y += 56 + 14
        if pk and pk.get("ok"):
            for i, band in enumerate(BANDS):
                items = pk["bands"][band]
                keys = [c["key"] if isinstance(c, dict) else c for c in items]
                lines = band_lines(len(keys))
                rh = lines * LINE_H + 22
                d.rectangle([MARGIN, y, W - MARGIN, y + rh - 1], fill="#f4f7fb" if i % 2 == 0 else "#ffffff")
                lab, rg = LABELS[band]
                d.text((MARGIN + 14, y + 22), lab, font=fonts.get(27), fill="#16273d", anchor="lm")
                d.text((MARGIN + 14, y + 56), f"{rg}", font=fonts.get(21, False), fill="#4a5a70", anchor="lm")
                d.text((MARGIN + 14, y + 84), f"{len(keys)}点", font=fonts.get(23), fill="#b3261e", anchor="lm")
                for j, k in enumerate(keys):
                    cx = MARGIN + LABEL_W + (j % per) * (CHIP_W + CHIP_GAP)
                    cy = y + 11 + (j // per) * LINE_H
                    draw_chip(d, cx, cy, k, fonts)
                y += rh
        else:
            d.rectangle([MARGIN, y, W - MARGIN, y + 79], fill="#f1f1f1")
            d.text((MARGIN + 18, y + 40), "このレースは、計算できませんでした", font=fonts.get(28), fill="#6b6b6b", anchor="lm")
            y += 80
        y += 22
    # 下の帯
    d.rectangle([0, total - FOOT, W, total], fill="#0f2742")
    d.text((W / 2, total - FOOT + 34), "直前情報を読み込んだ買い目・オリジナル出走表は、こちら", font=fonts.get(26), fill="#ffffff", anchor="mm")
    d.text((W / 2, total - FOOT + 70), "https://boat-rex-pro.com/", font=fonts.get(30), fill="#ffd54a", anchor="mm")
    # 色数を減らして、ファイルを軽くする(べた塗りの絵なので、見た目はほぼ変わらない。メールで送れる大きさに収めるため)
    img = img.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    img.save(path, "PNG", optimize=True)
    return total


def load_cards(bsp):
    p = os.path.join(bsp, "data", "race_card_latest.json")
    d = json.load(open(p, encoding="utf-8"))
    ds = sorted(d.keys())[-1]
    return ds, d[ds]


def compute_picks(bsp, ds, races):
    sys.path.insert(0, os.path.abspath(bsp))
    import news_picks      # 非公開側の部品(出走表サイトと同じ計算)
    global BANDS, LABELS
    BANDS, LABELS = list(news_picks.BANDS), dict(news_picks.LABELS)
    out = {}
    for r in news_picks.compute(races, ds, repo_dir=bsp):
        out[(r["venue"], r["race_no"])] = r
    return out


def build_mail(date, nvenue, nimg, nng, zip_path, subject_title):
    m, dd = date.month, date.day
    body = (
        f"■ タイトル欄\n{subject_title}\n\n"
        f"■ 見出し\n解析ツール BOAT REX PRO\n\n"
        f"■ 小見出し\n{m}月{dd}日 全レース買い目\n\n"
        f"■ 本文(定型)\n{TEMPLATE}\n\n"
        f"■ 画像\n添付のZIPを展開し、中の画像をすべて選んで、noteの本文にまとめてドラッグしてください。\n\n"
        f"(ここから下は、貼り付け不要)\n開催{nvenue}場 ・ 画像{nimg}枚 ・ 計算できなかったレース {nng}\n"
    )
    return body


def send_mail(user, to, pw, subject, body, zip_path):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with open(zip_path, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="zip")
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", os.path.basename(zip_path)))
    msg.attach(part)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=120) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bsp", default="bsp", help="非公開側(boat-scenario-pro)を取り出したフォルダ")
    ap.add_argument("--out", default="note_out")
    ap.add_argument("--force", action="store_true", help="送信済みでも・日付が今日でなくても、作って送る")
    ap.add_argument("--no-mail", action="store_true", help="メールを送らない(画像と文面だけ作る)")
    ap.add_argument("--picks-json", default="", help="試験用: 計算の代わりに、この買い目のファイルを使う")
    ap.add_argument("--per-image", type=int, default=PER_IMAGE, help="1枚の画像に入れるレース数(標準6。noteで縦長が見づらいときは、3や4に)")
    a = ap.parse_args()

    ds, day = load_cards(a.bsp)
    today = datetime.now(JST).strftime("%Y%m%d")
    if ds != today and not a.force:
        log(f"::error::出走表のデータが今日のものではありません(データの日付 {ds} / 今日 {today})。古い買い目は送りません")
        return 1
    date = datetime.strptime(ds, "%Y%m%d").date()
    rec = os.path.join("uploaded", f"{ds}_note_mail.json")
    if os.path.exists(rec) and not a.force and not a.no_mail:
        log(f"[skip] {ds} は送信済みです({rec})")
        return 0

    races = []
    for code in sorted(day.keys()):
        for rno in sorted(day[code].keys(), key=int):
            races.append({"venue": NAME[code], "race_no": int(rno)})
    log(f"出走表: {len({r['venue'] for r in races})}場 / {len(races)}レース({ds})")

    if a.picks_json:
        raw = json.load(open(a.picks_json, encoding="utf-8"))
        picks = {(k.split("|")[0], int(k.split("|")[1])): v for k, v in raw.items()}
    else:
        picks = compute_picks(a.bsp, ds, races)
    nok = sum(1 for r in races if picks.get((r["venue"], r["race_no"]), {}).get("ok"))
    nng = len(races) - nok
    log(f"買い目: {nok}レース / 計算できなかった {nng}レース")
    if nok == 0:
        ex = next((v.get("reason") for v in picks.values() if v.get("reason")), "")
        log(f"::error::買い目を1レースも計算できませんでした({ex})。メールは送りません")
        return 1

    os.makedirs(a.out, exist_ok=True)
    for f in glob.glob(os.path.join(a.out, "*")):
        os.remove(f)
    fonts = Fonts()
    files = []
    venues = sorted({r["venue"] for r in races}, key=lambda v: VENUE_CODE[v])
    for v in venues:
        nos = sorted(r["race_no"] for r in races if r["venue"] == v)
        groups = {}
        for n in nos:      # 1〜6R・7〜12R(欠けたレースがあっても、レース番号で分ける)
            groups.setdefault((n - 1) // max(1, a.per_image), []).append(n)
        for gi in sorted(groups):
            grp = groups[gi]
            pk = {n: picks.get((v, n)) for n in grp}
            name = f"{VENUE_CODE[v]}_{v}_{grp[0]}-{grp[-1]}R.png"
            p = os.path.join(a.out, name)
            h = render_image(p, date, v, grp, pk, fonts)
            files.append(p)
            log(f"  画像 {name}  高さ {h}px  {os.path.getsize(p) // 1024}KB")
    zip_path = os.path.join(a.out, f"boat-note-{ds}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for p in files:
            z.write(p, os.path.basename(p))
    zsize = os.path.getsize(zip_path)
    log(f"ZIP: {os.path.basename(zip_path)}  画像{len(files)}枚  {zsize / 1024 / 1024:.1f}MB")
    if zsize > 18 * 1024 * 1024:
        log(f"::error::ZIPが大きすぎて({zsize / 1024 / 1024:.1f}MB)メールで送れません")
        return 1

    title = f"【{date.month}月{date.day}日】全レース買い目|解析ツール BOAT REX PRO"
    body = build_mail(date, len(venues), len(files), nng, zip_path, title)
    with open(os.path.join(a.out, "mail_body.txt"), "w", encoding="utf-8") as f:
        f.write(f"件名: {title}\n\n{body}")
    if a.no_mail:
        log("[no-mail] メールは送りません")
        return 0

    user = os.environ.get("MAIL_USER", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not pw:
        log("::error::GMAIL_APP_PASSWORD(または MAIL_USER)が登録されていないため、メールを送れません")
        return 1
    try:
        send_mail(user, to, pw, title, body, zip_path)
    except smtplib.SMTPAuthenticationError:
        log("::error::Gmailにログインできませんでした。GMAIL_APP_PASSWORD が正しいか確認してください")
        return 1
    except Exception as e:
        log(f"::error::メールを送れませんでした: {type(e).__name__}: {e}")
        return 1
    os.makedirs("uploaded", exist_ok=True)
    jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    with open(rec, "w", encoding="utf-8") as f:
        json.dump({"to": to, "subject": title, "images": len(files), "ng": nng, "at": jst}, f, ensure_ascii=False, indent=1)
    log(f"[mail] 送りました: {to}  件名={title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
