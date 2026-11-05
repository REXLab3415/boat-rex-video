#!/usr/bin/env python3
"""BOAT REX PRO 答え合わせ動画(本番)ビルダー  ※公開リポジトリ(boat-rex-video)用

材料: days/日付.json(非公開側の全レース検証が、保存のたびに送ってくる。場・レース・結果・払戻金・各帯の買い目)
流れ: 読み込み → 台本(冒頭 → 全レース → 最後) → 音声(VOICEVOX 青山龍星) → 口パク用タイムライン
      → HTMLを1コマずつ撮影(Playwright) → ffmpegでmp4化 → 概要欄の文章(場ごとのチャプターつき)
声・口パク・キャスター・背景は、build_video.py と assets/ の部品を使う。

使い方:
  python build_allrace_video.py --date 20261102 --voice voicevox
  確認用(VOICEVOXなし・無音): --voice dummy      静止画だけ: --stills 3,10,20
"""
import argparse
import collections
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_video as V  # noqa: E402  (声・口パク・撮影の部品)
import numpy as np  # noqa: E402

BANDS = [("prob", "確率(高)"), ("hm", "確率(高)〜(中)"), ("bal", "確率(中)"), ("ml", "確率(中)〜(低)"), ("ev", "確率(低)")]
MIN_DUR_RACE = 7.0
SITE_URL = "https://boat-scenario-pro.sg34153415.workers.dev"

BASE_TAGS = ["競艇", "ボートレース", "ボートレース結果", "3連単", "払戻金", "結果", "答え合わせ", "万舟", "BOAT REX PRO"]
MIN_CHAPTER = 10        # YouTubeのチャプターは、1つ10秒以上(これ未満があると、全体が無効になる)


def mmss(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def build_chapters(beats, total):
    """各場の最初の音声の開始(実測)から、チャプターを作る。10秒未満になる章は外す(最初の章だけは、次の章とまとめる)"""
    ch = [["オープニング", int(beats[0]["start"])]]
    seen = set()
    for bt in beats:
        v = bt["race"]["venue"] if bt["type"] == "race" else bt.get("venue") if bt["type"] == "fail" else None
        if v and v not in seen:
            seen.add(v)
            ch.append([v, int(bt["start"])])
    ends = [b for b in beats if b["type"] == "ending"]
    if ends:
        ch.append(["エンディング", int(ends[0]["start"])])
    end_t = int(total)
    while True:
        bad = None
        for i, (_, t) in enumerate(ch):
            nxt = ch[i + 1][1] if i + 1 < len(ch) else end_t
            if nxt - t < MIN_CHAPTER:
                bad = i
                break
        if bad is None or len(ch) <= 1:
            break
        if bad == 0 and len(ch) > 1:
            print(f"::warning::「{ch[0][0]}」が10秒未満のため、次の「{ch[1][0]}」とまとめました")
            ch[0][0] = f"{ch[0][0]}・{ch[1][0]}"
            del ch[1]
        else:
            print(f"::warning::チャプター「{ch[bad][0]}」が10秒未満のため、チャプターから外しました")
            del ch[bad]
    if len(ch) < 3:
        print("::warning::チャプターが3つ未満のため、チャプターは付けません(YouTubeの条件)")
        return []
    return [f"{mmss(t)} {name}" for name, t in ch]


def build_youtube_meta(date, day, races, beats, total, partial=False):
    """タイトル・概要欄・タグ。値はすべて、その日のデータ(days/日付.json)と、動画の実測の時刻から作る"""
    m, d = int(date[4:6]), int(date[6:])
    venues = list(day["venues"])
    nfails = len(day.get("fails", []))
    hit_races = [r for r in races if r["hit"]]
    nhit = len(hit_races)
    top = max(hit_races, key=lambda r: int(r["pay"])) if hit_races else None      # ツールが的中したレースの中の最高払戻(同額なら最初のレース)
    maxpay = int(top["pay"]) if top else 0
    zen = "全" if (day.get("scope") == "全場" and nfails == 0 and not partial) else ""   # 「全」は、動画に入っている範囲が全場・全レースのときだけ
    nv, nr = len(venues), len(races)
    title = f"【ボートレース結果】{m}/{d} {zen}{nv}場{zen}{nr}Rの3連単結果と払戻金|的中{nhit}件・最高{maxpay:,}円" if nhit else f"【ボートレース結果】{m}/{d} {zen}{nv}場{zen}{nr}Rの3連単結果と払戻金|的中0件"
    if len(title) > 100:
        raise ValueError(f"タイトルが100文字を超えました({len(title)}文字)")
    chapters = build_chapters(beats, total)
    lines = [f"{m}/{d}のボートレース{zen}{nv}場{zen}{nr}Rの3連単結果と払戻金を、ボートレース解析ツール「BOAT REX PRO」で照らし合わせ。"
             f"的中は{nhit}件でした。", ""]
    if chapters:
        lines += ["■チャプター"] + chapters + [""]
    lines += ["■ボートレース解析ツール BOAT REX PRO",
              "レースの展開を解析し、買い目を出すボートレース解析ツールです。この動画では、その買い目を実際の結果と照らし合わせています。",
              f"公式サイト: {SITE_URL}", "",
              "■クレジット", "VOICEVOX:青山龍星", "",
              "#ボートレース #競艇 #3連単"]
    tags = list(BASE_TAGS)
    for v in venues:
        if v not in tags:
            tags.append(v)
    while sum(len(t) + (2 if " " in t else 0) for t in tags) + len(tags) - 1 > 480 and len(tags) > len(BASE_TAGS):
        print(f"::warning::タグが500文字に収まらないため、「{tags[-1]}」を外しました")
        tags.pop()
    return {"date": date, "title": title, "description": "\n".join(lines) + "\n", "tags": tags,
            "maxpay": maxpay, "maxVenue": top["venue"] if top else None, "maxNo": top["no"] if top else None, "nhit": nhit, "nvenues": nv, "nraces": nr}



def latest_date():
    base = os.path.join(HERE, "days")
    names = sorted(n[:-5] for n in os.listdir(base) if n.endswith(".json") and len(n) == 13 and n[:8].isdigit()) if os.path.isdir(base) else []
    return names[-1] if names else ""


def load_day(date):
    with open(os.path.join(HERE, "days", f"{date}.json"), encoding="utf-8") as f:
        return json.load(f)


def q_total(q):
    t = q.get("prePhonemeLength", 0.0) + q.get("postPhonemeLength", 0.0)
    for ap in q["accent_phrases"]:
        for m in ap["moras"]:
            t += (m.get("consonant_length") or 0.0) + (m.get("vowel_length") or 0.0)
        if ap.get("pause_mora"):
            t += ap["pause_mora"]["vowel_length"]
    return t


def seg_fractions(voice, segs):
    """文ごとの読み上げの長さの比(3連単・払戻金・判定を、声のタイミングに合わせるため)。"""
    ds = []
    for t in segs:
        if voice.mode == "voicevox":
            import json as _j, urllib.parse as _u
            q = _j.loads(voice._post(f"/audio_query?text={_u.quote(t)}&speaker={voice.speaker}"))
        else:
            q = V.dummy_synth(t)[1]
        ds.append(q_total(q))
    tot = sum(ds) or 1.0
    out, c = [], 0.0
    for d in ds:
        out.append(c / tot)
        c += d
    return out          # 各文の、開始位置(0〜1)


FAIL_REASON = {
    "fault": ("システムに不具合が起きたため", "大変申し訳ありません"),
    "absent": ("欠場艇が出たため", ""),
    "noresult": ("結果が出ていないため", ""),
    "special": ("同着などのため", ""),
}


def region(a, b):
    """飛ばした範囲の言い方(whole=その場すべて / 以降 / 1レース / 範囲)"""
    if a == 1 and b == 12:
        return "", "全レース", "ボートは"
    if b == 12 and a < 12:
        return f"、{a}レース以降は", f"{a}レース以降", ""
    if a == b:
        return f"、{a}レースは", f"{a}レース", ""
    return f"、{a}レースから、{b}レースは", f"{a}〜{b}レース", ""


def fail_beat(venue, a, b, kind):
    why, sorry = FAIL_REASON.get(kind, FAIL_REASON["fault"])
    mid, label, whole = region(a, b)
    if whole:       # その場すべて
        text = f"{venue}ボートは、{why}、お伝えすることができません。"
    else:
        text = f"{venue}ボート{mid}、{why}、お伝えすることができません。"
    if sorry:
        text += sorry + "。"
    return {"type": "fail", "venue": venue, "label": label, "kind": kind, "text": text,
            "msg1": f"{why}、お伝えすることができません", "msg2": sorry}


def race_text(r, lead=""):
    a, b, c = r["win"].split("-")
    s1 = f"{lead}{r['venue']}ボート、{r['no']}レース。"
    s2 = f"3連単、{a}、{b}、{c}。"
    s3 = f"払戻金、{r['pay']}円。"
    s4 = "ツールの買い目、的中です。" if r["hit"] else "ツールの買い目に、的中はありません。"
    return s1, s2, s3, s4


def build_script(date, day, brand_reading):
    m, d = int(date[4:6]), int(date[6:])
    beats = [{"type": "opening", "text": f"{m}月{d}日、解析ツール、{brand_reading}、答え合わせの時間です。"}]
    by_race = {(r["venue"], r["no"]): r for r in day["races"]}
    by_fail = {(f["venue"], f["no"]): f["kind"] for f in day.get("fails", [])}
    after_fail = False
    for v in day["venues"]:
        n = 1
        while n <= 12:
            r = by_race.get((v, n))
            if r:
                segs = race_text(r, "続いて、" if after_fail else "")
                beats.append({"type": "race", "race": r, "segs": list(segs), "text": "".join(segs)})
                after_fail = False
                n += 1
                continue
            kind = by_fail.get((v, n), "fault")
            e = n
            while e + 1 <= 12 and (v, e + 1) not in by_race and by_fail.get((v, e + 1), "fault") == kind:
                e += 1
            beats.append(fail_beat(v, n, e, kind))
            after_fail = True
            n = e + 1
    beats.append({"type": "ending", "text": f"解析ツール、{brand_reading}の詳細は、概要欄からご確認ください。それでは、また明日、お会いしましょう。"})
    return beats


def assemble(beats, voice, last_tail=1.4):
    cursor, sr_ref, chunks = 0.0, None, []
    for i, b in enumerate(beats):
        wav, q = voice.synth(b["text"])
        a, sr = V.read_wav(wav)
        sr_ref = sr_ref or sr
        assert sr == sr_ref
        alen = len(a) / sr
        b["audioLen"] = round(alen, 3)
        b["audioOffset"] = V.LEAD
        b["visemes"], b["lipsync"] = V.pick_visemes(q, a, sr, alen, f'{i + 1}番目 {b["type"]}')
        tail = last_tail if i == len(beats) - 1 else V.TAIL
        mind = {"opening": 5.0, "race": MIN_DUR_RACE, "fail": 5.0, "ending": 5.0}[b["type"]]
        b["dur"] = round(max(mind, V.LEAD + alen + tail), 3)
        b["start"] = round(cursor, 3)
        chunks.append((cursor + V.LEAD, a))
        if b["type"] == "race":
            f = seg_fractions(voice, b["segs"])      # 文の開始位置
            b["triTime"] = round(V.LEAD + alen * f[1], 3)
            b["payTime"] = round(V.LEAD + alen * f[2], 3)
            b["verdictTime"] = round(V.LEAD + alen * f[3], 3)
            del b["segs"]
        cursor += b["dur"]
    total = cursor
    master = np.zeros(int(total * sr_ref) + sr_ref, dtype=np.int16)
    for off, a in chunks:
        i0 = int(off * sr_ref)
        master[i0:i0 + len(a)] = a
    return total, master, sr_ref


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="例 20261102。空欄なら、保存のある、いちばん新しい日")
    ap.add_argument("--voice", choices=["voicevox", "dummy"], default="voicevox")
    ap.add_argument("--voicevox-url", default="http://127.0.0.1:50021")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--brand", default="BOAT REX PRO")
    ap.add_argument("--brand-reading", default="ボートレックスプロ")
    ap.add_argument("--limit", type=int, default=0, help="確認用: 最初のNレースだけ")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--stills", default="")
    ap.add_argument("--max-sec", type=float, default=0)
    args = ap.parse_args()

    date = args.date or latest_date()
    if not date or not os.path.exists(os.path.join(HERE, "days", f"{date}.json")):
        print(f"::notice::days/{date or '(日付なし)'}.json がありません。動画は作りません")
        return 0
    day = load_day(date)
    races = day["races"]
    if not races:
        print(f"::notice::{date} は、答え合わせできたレースがありません。動画は作りません")
        return 0
    if args.limit:                      # 確認用: 最初のNレースだけ(飛ばしたレースの案内は、出さない)
        races = races[:args.limit]
        day = dict(day, races=races, fails=[], venues=[v for v in day["venues"] if any(r["venue"] == v for r in races)])
    move1 = day["move1"]
    venues = list(day["venues"])
    nfails = len(day.get("fails", []))
    y, m, d = int(date[:4]), int(date[4:6]), int(date[6:])
    os.makedirs(args.out, exist_ok=True)
    nhit = sum(1 for r in races if r["hit"])
    print(f"[data] {date} {'・'.join(venues)} races={len(races)} 的中あり={nhit} 的中なし={len(races) - nhit} お伝えできないレース={nfails}")

    beats = build_script(date, day, args.brand_reading)
    voice = V.Voice(args.voice, args.voicevox_url)
    total, master, sr = assemble(beats, voice)
    cnt = collections.Counter(b["lipsync"] for b in beats)
    label = {"mora": "通常(VOICEVOXの計画表)", "audio": "音量の波形(保険)", "none": "動かない(無音)"}
    summary = "口パクの方式: " + " / ".join(f"{label[k]} {v}か所" for k, v in cnt.items())
    print(f"[lipsync] {summary}")
    if set(cnt) != {"mora"}:
        print(f"::warning title=口パクの方式を切り替えました::{summary}", flush=True)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(f"### {date} の動画\n全{len(races)}レース(的中あり {nhit} / 的中なし {len(races) - nhit})・長さ {total / 60:.1f}分\n\n{summary}\n")
    audio_path = os.path.join(args.out, "narration.wav")
    V.write_wav(audio_path, master, sr)

    data = {
        "date": date, "dateLabel": f"{m}月{d}日", "venueText": "・".join(venues), "nraces": len(races),
        "move1": move1, "brand": args.brand, "nvenues": len(venues), "beats": beats,
        "bands": day["bands"],
        "ticker": [f"{r['venue']} {r['no']}R <b>{r['win']}</b> ¥{r['pay']:,}" for r in races],
    }
    with open(os.path.join(HERE, "assets", "caster.json"), encoding="utf-8") as f:
        data["caster"] = json.load(f)
    with open(os.path.join(HERE, "assets", "layout.json"), encoding="utf-8") as f:
        data["layout"] = json.load(f)
    with open(os.path.join(HERE, "signboard.txt"), encoding="utf-8") as f:
        data["sign"] = [ln.strip() for ln in f if ln.strip()]
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(args.out, "assets"), dirs_exist_ok=True)
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        html = f.read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    html_path = os.path.join(args.out, "scene.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(args.out, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    try:
        meta = build_youtube_meta(date, day, races, beats, total, partial=bool(args.limit))
    except Exception as e:           # 作れなくても、動画は作る。投稿は止まる(投稿側が、youtube_meta.json がないことを検知する)
        print(f"::error::タイトル・概要欄を作れませんでした({type(e).__name__}: {e})。動画は作りますが、YouTubeへは投稿されません")
        meta = None
    if meta:
        with open(os.path.join(args.out, "youtube_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        with open(os.path.join(args.out, "description.txt"), "w", encoding="utf-8") as f:
            f.write(meta["description"])
    print(f"[timeline] total {total:.1f}s ({total / 60:.1f}分)  races={len(races)}")

    stills = [float(x) for x in args.stills.split(",")] if args.stills else None
    out_mp4 = os.path.join(args.out, f"boat_check_{date}.mp4")
    height = int(round(args.width * 9 / 16))
    V.render(html_path, total, args.fps, args.width, height, out_mp4, audio_path,
             stills=stills, still_dir=os.path.join(args.out, "stills"), max_sec=args.max_sec or None)
    if not stills:
        print(f"[done] {out_mp4}  ({os.path.getsize(out_mp4) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
