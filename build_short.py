#!/usr/bin/env python3
"""BOAT REX PRO ショート動画(縦1080x1920・59秒以内)ビルダー  ※公開リポジトリ(boat-rex-video)用

材料: days/日付.json だけ。その日の最高払戻のレース1本を取り上げる(ツールの買い目が外れたときは、外れたと出す)。
流れ: 読み込み → 台本(5つ) → 音声(VOICEVOX 青山龍星) → 口パク用タイムライン → HTMLを1コマずつ撮影 → ffmpegでmp4化
      → タイトル・概要欄・タグ(out/short_meta.json)
値が取れないときは、固定値で埋めず、ショートを作らずに止める(終了コード1。横動画には影響しない)。

使い方:
  python build_short.py --date 20261102 --voice voicevox --out out
  確認用: --voice dummy(無音)   静止画だけ: --stills 0,8,16,24
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_video as V  # noqa: E402  (声・口パク)
import build_allrace_video as A  # noqa: E402  (日付・データの読み込み)
import numpy as np  # noqa: E402

W, H = 1080, 1920
MAX_SEC = 59.0          # ショートの上限(YouTubeの公式は3分だが、余裕を持って59秒以内にする)
MIN_BEAT = [6.0, 5.5, 5.5, 7.0, 6.0]      # 5つの場面の最短の長さ(合計30秒。目標は30〜50秒)
SITE_URL = A.SITE_URL
BASE_TAGS = ["競艇", "ボートレース", "ボートレース結果", "3連単", "払戻金", "万舟", "BOAT REX PRO", "Shorts"]
BAND_SPOKEN = {"prob": "確率が高い帯", "hm": "確率が高めから、中くらいの帯", "bal": "確率が中くらいの帯",
               "ml": "確率が中くらいから、低めの帯", "ev": "確率が低い帯"}


class ShortError(Exception):
    pass


def need(cond, msg):
    if not cond:
        raise ShortError(msg)


def pick_top(day):
    """最高払戻のレース1本(同額が複数なら、最初のレース)。取れない値があれば、止める"""
    races = day.get("races") or []
    need(races, "答え合わせできたレースがありません")
    for r in races:
        for k in ("venue", "no", "win", "pay", "bandHit"):
            need(k in r, f"{r.get('venue')}{r.get('no')}Rに「{k}」がありません")
    top = max(races, key=lambda r: int(r["pay"]))          # max は、同額なら最初のものを返す
    need(str(top["win"]).count("-") == 2 and all(x.isdigit() and 1 <= int(x) <= 6 for x in str(top["win"]).split("-")),
         f"3連単の形が正しくありません({top['win']})")
    need(int(top["pay"]) > 0, f"払戻金が正しくありません({top['pay']})")
    bands = day.get("bands") or []
    need(len(bands) == 5 and all(b["key"] in top["bandHit"] for b in bands), "帯の情報が揃っていません")
    return top, bands


def spoken_bands(hit_keys):
    n = len(hit_keys)
    if n == 5:
        return "5つの帯すべて"
    if n >= 3:
        return f"{n}つの帯"
    return "と、".join(BAND_SPOKEN[k] for k in hit_keys)


def build_beats(date, day, top, bands, compact):
    m, d = int(date[4:6]), int(date[6:])
    a, b, c = str(top["win"]).split("-")
    hit_keys = [bd["key"] for bd in bands if top["bandHit"][bd["key"]]]
    if hit_keys:
        verdict = f"ツールの買い目、的中です。" if compact else f"ツールの買い目は、{spoken_bands(hit_keys)}で、的中です。"
    else:
        verdict = "ツールの買い目に、的中はありません。"
    all_venues = day.get("scope") == "全場" and not day.get("fails")
    if compact:
        end = "答え合わせは、チャンネルの最新動画で。"
    else:
        end = ("全場の答え合わせは、チャンネルの最新動画で。" if all_venues
               else "ほかのレースの答え合わせは、チャンネルの最新動画で。")
    texts = [f"{m}月{d}日の、最高払戻は、{top['venue']}ボート、{top['no']}レース。",
             f"3連単、{a}、{b}、{c}。",
             f"払戻金、{top['pay']}円。",
             verdict, end]
    types = ["opening", "tri", "pay", "verdict", "ending"]
    return [{"type": t, "text": x, "min": MIN_BEAT[i]} for i, (t, x) in enumerate(zip(types, texts))], hit_keys, all_venues


def assemble(beats, voice, last_tail=1.4):
    cursor, sr_ref, chunks = 0.0, None, []
    for i, bt in enumerate(beats):
        wav, q = voice.synth(bt["text"])
        a, sr = V.read_wav(wav)
        sr_ref = sr_ref or sr
        assert sr == sr_ref
        alen = len(a) / sr
        bt["audioLen"] = round(alen, 3)
        bt["audioOffset"] = V.LEAD
        bt["visemes"], bt["lipsync"] = V.pick_visemes(q, a, sr, alen, f"ショート{i + 1}番目 {bt['type']}")
        tail = last_tail if i == len(beats) - 1 else V.TAIL
        bt["dur"] = round(max(bt["min"], V.LEAD + alen + tail), 3)
        bt["start"] = round(cursor, 3)
        chunks.append((cursor + V.LEAD, a))
        cursor += bt["dur"]
    total = cursor
    master = np.zeros(int(total * sr_ref) + sr_ref, dtype=np.int16)
    for off, a in chunks:
        i0 = int(off * sr_ref)
        master[i0:i0 + len(a)] = a
    return total, master, sr_ref


def render(html_path, total, fps, out_mp4, audio_path, stills=None, still_dir=None):
    import math
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--font-render-hinting=none"])
        pg = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.goto("file://" + os.path.abspath(html_path))
        pg.wait_for_function("document.fonts.ready.then(()=>true)")
        pg.wait_for_function("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        pg.wait_for_timeout(300)
        if stills:
            os.makedirs(still_dir, exist_ok=True)
            for s in stills:
                pg.evaluate(f"render({s})")
                pg.screenshot(path=os.path.join(still_dir, f"short_still_{s:06.2f}.png"))
            br.close()
            return
        n = int(math.ceil(total * fps))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
               "-i", audio_path, "-t", f"{total:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
               "-r", str(fps), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4]
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(n):
            pg.evaluate(f"render({i / fps:.4f})")
            ff.stdin.write(pg.screenshot(type="jpeg", quality=90))
            if i % 150 == 0:
                print(f"[short render] {i}/{n} frames", flush=True)
        ff.stdin.close()
        rc = ff.wait()
        br.close()
        if rc != 0:
            raise ShortError(f"ffmpegが失敗しました(exit {rc})")


def build_meta(date, day, top, bands, hit_keys):
    m, d = int(date[4:6]), int(date[6:])
    pay = int(top["pay"])
    title = f"{top['venue']}{top['no']}R 3連単{pay:,}円|{m}/{d}ボートレース結果"
    need(len(title) <= 100, f"タイトルが100文字を超えました({len(title)}文字)")
    if hit_keys:
        labels = "・".join(bd["label"] for bd in bands if top["bandHit"][bd["key"]])
        verdict = f"ツールの買い目は、{labels}の帯で的中でした。"
    else:
        verdict = "ツールの買い目は、的中なしでした。"
    lines = []
    rec = os.path.join(HERE, "uploaded", f"{date}.json")
    if os.path.exists(rec):
        try:
            vid = json.load(open(rec, encoding="utf-8")).get("videoId")
        except Exception:
            vid = None
        if vid:
            lines += [f"全レースの結果はこちら→ https://www.youtube.com/watch?v={vid}", ""]
    if not lines:
        print("::notice::横動画の投稿の記録(uploaded/日付.json)がないため、概要欄に横動画のリンクは入れません")
    lines += [f"{m}/{d}のボートレース、最高払戻金は{top['venue']}{top['no']}Rの3連単{top['win']}、100円あたり{pay:,}円。"
              f"ボートレース解析ツール「BOAT REX PRO」の買い目で答え合わせ。{verdict}",
              f"公式サイト: {SITE_URL}", "",
              "■クレジット", "VOICEVOX:青山龍星", "",
              "#Shorts #ボートレース #競艇 #3連単"]
    tags = list(BASE_TAGS)
    if top["venue"] not in tags:
        tags.append(top["venue"])
    return {"date": date, "title": title, "description": "\n".join(lines) + "\n", "tags": tags,
            "venue": top["venue"], "no": top["no"], "pay": pay, "win": top["win"], "hit": bool(hit_keys)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="例 20261102。空欄なら、保存のある、いちばん新しい日")
    ap.add_argument("--voice", choices=["voicevox", "dummy"], default="voicevox")
    ap.add_argument("--voicevox-url", default="http://127.0.0.1:50021")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--brand", default="BOAT REX PRO")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--stills", default="")
    args = ap.parse_args()

    date = args.date or A.latest_date()
    if not date or not os.path.exists(os.path.join(HERE, "days", f"{date}.json")):
        print(f"::notice::days/{date or '(日付なし)'}.json がありません。ショートは作りません")
        return 0
    try:
        day = A.load_day(date)
        top, bands = pick_top(day)
        os.makedirs(args.out, exist_ok=True)
        voice = V.Voice(args.voice, args.voicevox_url)
        total = None
        for compact in (False, True):
            beats, hit_keys, all_venues = build_beats(date, day, top, bands, compact)
            total, master, sr = assemble(beats, voice)
            print(f"[short] 台本={'短い版' if compact else '通常版'} 長さ {total:.1f}秒")
            if total <= MAX_SEC:
                break
            print(f"::warning::ショートの長さが{MAX_SEC:.0f}秒を超えたので、台本を短くします({total:.1f}秒)")
        need(total <= MAX_SEC, f"台本を短くしても{MAX_SEC:.0f}秒を超えました({total:.1f}秒)。ショートは上げません")

        m, d = int(date[4:6]), int(date[6:])
        audio_path = os.path.join(args.out, "short_narration.wav")
        V.write_wav(audio_path, master, sr)
        pay = int(top["pay"])
        verdict_at = beats[3]["start"] + V.LEAD + (0.9 if hit_keys else 0.7)
        data = {
            "date": date, "dateLabel": f"{m}/{d}", "brand": args.brand, "venue": top["venue"], "no": top["no"],
            "win": str(top["win"]).split("-"), "payText": f"{pay:,}", "nohit": not hit_keys, "verdictAt": round(verdict_at, 3),
            "bands": [{"label": bd["label"], "lo": bd["lo"], "hi": bd["hi"], "hit": bool(top["bandHit"][bd["key"]])} for bd in bands],
            "bubble": (["全場の答え合わせは", "チャンネルの最新動画で"] if (beats[4]["text"].startswith("全場"))
                       else ["ほかのレースの答え合わせは", "チャンネルの最新動画で"] if beats[4]["text"].startswith("ほか")
                       else ["答え合わせは", "チャンネルの最新動画で"]),
            "beats": beats,
        }
        with open(os.path.join(HERE, "assets", "caster.json"), encoding="utf-8") as f:
            data["caster"] = json.load(f)
        import shutil
        shutil.copytree(os.path.join(HERE, "assets"), os.path.join(args.out, "assets"), dirs_exist_ok=True)
        with open(os.path.join(HERE, "short_template.html"), encoding="utf-8") as f:
            html = f.read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
        html_path = os.path.join(args.out, "short_scene.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        meta = build_meta(date, day, top, bands, hit_keys)
        with open(os.path.join(args.out, "short_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)

        stills = [float(x) for x in args.stills.split(",")] if args.stills else None
        out_mp4 = os.path.join(args.out, f"short_{date}.mp4")
        render(html_path, total, args.fps, out_mp4, audio_path, stills=stills, still_dir=os.path.join(args.out, "stills"))
        if not stills:
            print(f"[short done] {out_mp4} ({os.path.getsize(out_mp4) / 1e6:.1f} MB, {total:.1f}秒) 取り上げたレース={top['venue']}{top['no']}R {pay:,}円 的中={'あり' if hit_keys else 'なし'}")
            sp = os.environ.get("GITHUB_STEP_SUMMARY")
            if sp:
                with open(sp, "a", encoding="utf-8") as f:
                    f.write(f"### {date} のショート\n{top['venue']}{top['no']}R・最高払戻 {pay:,}円・ツールの買い目 {'的中あり' if hit_keys else '的中なし'}・長さ {total:.1f}秒\n")
        return 0
    except ShortError as e:
        print(f"::error title=ショートを作れませんでした::{e}(横動画には影響しません)")
        return 1
    except Exception as e:      # 想定外でも、横動画は止めない
        print(f"::error title=ショートを作れませんでした::{type(e).__name__}: {e}(横動画には影響しません)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
