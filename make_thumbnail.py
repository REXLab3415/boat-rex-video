#!/usr/bin/env python3
"""days/日付.json から、YouTubeのサムネイル(1280x720のJPEG)を作る。
  python make_thumbnail.py --date 20261102 --out out   → out/thumbnail_20261102.jpg
作れなくても、動画の投稿は止めない(呼ぶ側で、失敗しても続ける)。
"""
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIMIT = 1_900_000   # YouTubeの上限は2MB


def build(date, out):
    with open(os.path.join(HERE, "days", f"{date}.json"), encoding="utf-8") as f:
        day = json.load(f)
    races = day["races"]
    if not races:
        print("::notice::レースがないので、サムネイルは作りません")
        return None
    m, d = int(date[4:6]), int(date[6:])
    data = {
        "dateLabel": f"{m}/{d}",
        "maxPay": max((int(r["pay"]) for r in races if r["hit"]), default=None),   # ツールが的中したレースの中の最高払戻。的中が0件なら、なし
        "nraces": len(races),
        "nhit": sum(1 for r in races if r["hit"]),
        "sub": f"{len(day['venues'])}場の3連単を、ツールの買い目で答え合わせ",
    }
    with open(os.path.join(HERE, "thumbnail_template.html"), encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__ASSETS__", "file://" + os.path.join(HERE, "assets").replace(os.sep, "/"))
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    os.makedirs(out, exist_ok=True)
    html_path = os.path.join(out, "thumbnail.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    jpg = os.path.join(out, f"thumbnail_{date}.jpg")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 720})
        pg.goto("file://" + os.path.abspath(html_path))
        pg.wait_for_function("document.fonts.ready.then(()=>true)")
        pg.wait_for_function("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for q in (92, 85, 75, 65):
            pg.screenshot(path=jpg, type="jpeg", quality=q)
            if os.path.getsize(jpg) <= LIMIT:
                break
        b.close()
    print(f"[thumbnail] {jpg} ({os.path.getsize(jpg) / 1e3:.0f} KB) ツール的中の最高払戻={'なし' if data['maxPay'] is None else format(data['maxPay'], ',')} 的中あり={data['nhit']}/{data['nraces']}")
    return jpg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    a = ap.parse_args()
    date = a.date
    if not date:
        mp = sorted(glob.glob(os.path.join(a.out, "boat_check_*.mp4")))
        if not mp:
            print("::notice::動画がないので、サムネイルは作りません")
            return 0
        date = re.search(r"(\d{8})", os.path.basename(mp[-1])).group(1)
    return 0 if build(date, a.out) else 0


if __name__ == "__main__":
    sys.exit(main())
