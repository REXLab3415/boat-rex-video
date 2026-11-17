#!/usr/bin/env python3
"""BOAT REX PRO ツール紹介ショート(縦1080x1920・59秒以内)ビルダー【テスト版】 ※公開リポジトリ(boat-rex-video)用
流れ: 日付で毎日違う内容を決める(レース・攻め筋・確率帯) → ツールの画面を台本の順に操作して撮る(tool_capture.py)
      → 声(キャスター4人のローテーション・口パクつき) → 動画(mp4)
使い方: python build_tool_short.py --date 20261117 --tool <boat-scenario-pro のフォルダ> --voice voicevox|dummy --out out
テスト版: 直前情報とオッズは仮の値(公式には接続しない)。YouTubeには上げない。
"""
import argparse, json, os, random, shutil, subprocess, sys, glob, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa
import build_video as V  # noqa
import casters  # noqa
import tool_capture as TC  # noqa

W, H, MAX_SEC = 1080, 1920, 59.0
LEAD, TAIL, LAST_TAIL, LOGO_SEC = 0.10, 0.12, 1.3, 1.5
MOVES = {1: ['先マイ', '抵抗', '2着残し', '3着残し', '凹み'], 2: ['壁追走', '差し', '直まくり', '凹み'], 3: ['まくり', 'まくり差し', '差し', '凹み'],
         4: ['まくり', 'まくり差し', '絞りまくり', '差し', '凹み'], 5: ['まくり', 'まくり差し', '絞りまくり', '外マイ', '最内差し', '展開突き（差し）', '凹み'],
         6: ['まくり', 'まくり差し', '絞りまくり', '外マイ', '最内差し', '展開突き（差し）']}
BUDGETS = [3000, 5000, 10000, 20000]


def pick_content(date, picks_path, skip=0, avoid=()):
    """毎日違う内容を、日付で決める(同じ日は、何度作っても同じ)。skip は、選べなかったときの次の候補。
    avoid は、過去30日に使った「コース|攻め筋|確率帯」。同じ組み合わせは避ける"""
    rnd = random.Random(int(date) * 100 + skip)
    for _ in range(200):
        pos = rnd.randint(1, 6)
        move = rnd.choice(MOVES[pos])
        tab = rnd.choice(TC.TABS)
        if f"{pos}|{move}|{tab[0]}" not in avoid: break
    return {"venue": None, "no": None, "pos": pos, "move": move, "tab": tab, "budget": rnd.choice(BUDGETS)}


OPEN = ["注目のレースは、{v}ボート、{n}レース。", "今回注目するのは、{v}ボート、{n}レース。", "ピックアップするレースは、{v}ボート、{n}レースです。"]
MOVE_LINE = ["このレースでは、{p}コース、{m}を選択していきます。", "攻め筋は、{p}コース、{m}でいきます。", "{p}コース、{m}の展開を想定して、選択します。"]
BAND_PRE = "今回は、こちらの確率帯を選択し、"        # 「中」の字を、セリフに入れない(読み間違いを避ける)
BAND_END = {"prob": ["堅実に狙っていきます。", "堅く狙っていきます。"],
            "hm": ["バランスよく狙っていきます。", "バランス重視で狙っていきます。"],
            "bal": ["ほどよい配当を狙っていきます。", "配当とのバランスを見て狙っていきます。"],
            "ml": ["やや高めの配当を狙っていきます。", "少し高めの配当を狙っていきます。"],
            "ev": ["高配当を狙っていきます。", "一発の高配当を狙っていきます。"]}
CLOSE = ["ツールの詳細、答え合わせ動画は、プロフィール欄のリンクから。", "ツールの詳細と、答え合わせ動画は、プロフィール欄のリンクからご覧ください。",
         "詳しいツールの説明と、答え合わせ動画は、プロフィール欄のリンクからどうぞ。"]


def beats_for(c, date):
    """言い回しは、日付で決める(同じ日は、何度作っても同じ)。変わるのは、冒頭・攻め筋・確率帯・最後の4か所"""
    rnd = random.Random(int(date) * 31 + 7)
    op, mv, cl = rnd.choice(OPEN), rnd.choice(MOVE_LINE), rnd.choice(CLOSE)
    bd = BAND_PRE + rnd.choice(BAND_END[c["tab"][0]])
    return [None, op.format(v=c["venue"], n=c["no"]), "レース場と、レース番号を選択します。", "直前情報を読み込んで、", "スリット隊形を予想します。",
            mv.format(p=c["pos"], m=TC.MOVE_SPOKEN.get(c["move"], c["move"])), bd, "解析実行ボタンを押して、", "資金配分ボタンを押します。",
            "予算を入力し、オッズを読み込みます。", "すぐに、資金配分された買い目が出ます。", cl]


# ---- 声: 青山龍星で調整したアクセントと抑揚の付き方を、その日のキャスターに写す ----
def synth_match(voice, text, gain, log):
    """青山龍星で読ませて取ったアクセントの位置・高低の動き(山と谷)を、その日のキャスター自身の声の高さの中心に合わせて写す。
    声質・声の高さそのもの・間のとり方は、キャスターのまま。青山龍星の日と、音声なしの確認用は、そのまま読ませる。"""
    if voice.mode != "voicevox":
        return voice.synth(text)
    if not hasattr(voice, "_aoyama"):
        voice._aoyama = casters.find_style_id(voice._get("/speakers"), casters.CASTERS[0])
    if voice._aoyama is None or voice._aoyama == voice.speaker:
        return voice.synth(text)
    import urllib.parse as up
    def aq(sp): return json.loads(voice._post(f"/audio_query?text={up.quote(text)}&speaker={sp}"))
    qa, qt = aq(voice._aoyama), aq(voice.speaker)
    qt["speedScale"], qt["prePhonemeLength"], qt["postPhonemeLength"] = 1.05, 0.05, 0.12
    pa = [[m["pitch"] for m in ap["moras"]] for ap in qa["accent_phrases"]]
    pt = [[m["pitch"] for m in ap["moras"]] for ap in qt["accent_phrases"]]
    acc_a, acc_t = [ap["accent"] for ap in qa["accent_phrases"]], [ap["accent"] for ap in qt["accent_phrases"]]
    same = [len(x) for x in pa] == [len(x) for x in pt]
    if not same:
        log.append(f"[抑揚] 区切りが青山龍星と違うため、そのまま読ませました: {text}")
    else:
        va = [p for x in pa for p in x if p > 0]; vt = [p for x in pt for p in x if p > 0]
        ma, mt = sum(va) / len(va), sum(vt) / len(vt)
        for ap_t, ap_a in zip(qt["accent_phrases"], qa["accent_phrases"]):
            for m_t, m_a in zip(ap_t["moras"], ap_a["moras"]):
                if m_t["pitch"] > 0 and m_a["pitch"] > 0:
                    m_t["pitch"] = mt + gain * (m_a["pitch"] - ma)
        log.append(f"[抑揚] アクセント位置 青山={acc_a} 本人の初期値={acc_t}{'(同じ)' if acc_a == acc_t else '(違い→青山の山谷に合わせました)'} / {text}")
    wav = voice._post(f"/synthesis?speaker={voice.speaker}", qt)
    return wav, qt


def assemble(texts, voice, gain=1.0, log=None):
    log = log if log is not None else []
    cursor, sr_ref, chunks, beats = 0.0, None, [], []
    for i, tx in enumerate(texts):
        if tx is None:
            beats.append({"text": "", "start": cursor, "dur": LOGO_SEC, "audioLen": 0, "audioOffset": 0, "visemes": []}); cursor += LOGO_SEC; continue
        wav, q = synth_match(voice, tx, gain, log)
        a, sr = V.read_wav(wav); sr_ref = sr_ref or sr
        alen = len(a) / sr
        vis, _ = V.pick_visemes(q, a, sr, alen, f"ツール紹介{i}番目")
        tail = LAST_TAIL if i == len(texts) - 1 else TAIL
        dur = round(LEAD + alen + tail, 3)
        beats.append({"text": tx, "start": round(cursor, 3), "dur": dur, "audioLen": round(alen, 3), "audioOffset": LEAD, "visemes": vis})
        chunks.append((cursor + LEAD, a)); cursor += dur
    master = np.zeros(int(cursor * sr_ref) + sr_ref, dtype=np.int16)
    for off, a in chunks:
        i0 = int(off * sr_ref); master[i0:i0 + len(a)] = a
    for l in log: print(l)
    return cursor, master, sr_ref, beats


def render(html_path, total, fps, out_mp4, audio_path, stills=None, still_dir=None):
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
                pg.evaluate(f"render({s})"); pg.screenshot(path=os.path.join(still_dir, f"tool_still_{s:06.2f}.png"))
            br.close(); return
        n = int(math.ceil(total * fps))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-", "-i", audio_path,
               "-t", f"{total:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-r", str(fps),
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4]
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(n):
            pg.evaluate(f"render({i / fps:.4f})"); ff.stdin.write(pg.screenshot(type="jpeg", quality=90))
            if i % 150 == 0: print(f"[tool short] {i}/{n}", flush=True)
        ff.stdin.close(); rc = ff.wait(); br.close()
        if rc: raise RuntimeError(f"ffmpegが失敗しました({rc})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True); ap.add_argument("--tool", required=True)
    ap.add_argument("--picks", default=""); ap.add_argument("--voice", choices=["voicevox", "dummy"], default="voicevox")
    ap.add_argument("--voicevox-url", default="http://127.0.0.1:50021"); ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default="out"); ap.add_argument("--history", default=""); ap.add_argument("--live", action="store_true", help="本物の直前情報・オッズで撮る(本番)。なしは、仮の値のテスト版"); ap.add_argument("--stills", default="")
    a = ap.parse_args()
    picks = None
    hist_path = a.history or os.path.join(HERE, "tool_short_history.json")
    hist = json.load(open(hist_path, encoding="utf-8")) if os.path.exists(hist_path) else []
    for p_ in glob.glob(os.path.join(HERE, "uploaded", "*_toolshort.json")):          # 投稿済みの記録(本番)
        try:
            r_ = json.load(open(p_, encoding="utf-8"))
            if r_.get("key"): hist.append({"date": os.path.basename(p_)[:8], "key": r_["key"]})
        except Exception: pass
    recent = {h["key"] for h in hist if int(h["date"]) < int(a.date) and int(h["date"]) >= int(a.date) - 100}   # 目安: 直近30日ぶん
    os.makedirs(a.out, exist_ok=True)
    cap_dir = os.path.join(a.out, "tool_frames")
    shutil.rmtree(cap_dir, ignore_errors=True)
    shots = info = c = None
    live = None; fixed_vn = (None, None)
    if a.live:
        import tool_live as TL
        ymd = TL.jst_ymd()
        if a.date != ymd and os.environ.get("ALLOW_OLD_DATE") != "1":
            print(f"::error::本物のデータで撮れるのは、日本時間の今日({ymd})だけです(指定: {a.date})"); return 1
        got = TL.pick_live(a.tool, a.date, int(a.date))
        if not got: return 1
        live, fixed_vn = got["live"], (got["venue"], got["no"])
    for skip in range(8):                                   # 選べない組み合わせだったときは、次の候補(毎回、同じ順で決まる)
        c = pick_content(a.date, picks, skip, recent)
        try:
            shots, info = TC.capture(a.tool, cap_dir, fixed_vn[0] or c["venue"], fixed_vn[1] or c["no"], c["pos"], c["move"], c["tab"][0], c["budget"], int(a.date) + skip, live=live)
            c["venue"], c["no"] = info["venue"], info["no"]
            break
        except RuntimeError as e:
            print(f"::warning::撮影をやり直します({c['venue']}{c['no']}R {c['pos']}コース{c['move']}): {e}")
    if not shots: print("::error::ツールの画面を撮れませんでした"); return 1
    print("[内容]", c["venue"], f"{c['no']}R", f"{c['pos']}コース{c['move']}", c["tab"][0], c["budget"], "円", info)
    entry = {"date": a.date, "key": f"{c['pos']}|{c['move']}|{c['tab'][0]}", "venue": c["venue"], "no": c["no"]}
    json.dump(entry, open(os.path.join(a.out, "tool_short_history_entry.json"), "w", encoding="utf-8"), ensure_ascii=False)
    voice = V.Voice(a.voice, a.voicevox_url, date=a.date)
    print(f"[caster] {voice.caster['id']}(声: {voice.caster['voice']})")
    total, master, sr, beats = assemble(beats_for(c, a.date), voice, float(os.environ.get('INTO_GAIN') or 1.0) if os.environ.get('MATCH_AOYAMA','1')=='1' else 0.0)
    print(f"[長さ] {total:.1f}秒")
    if total > MAX_SEC: print(f"::error::{MAX_SEC:.0f}秒を超えました({total:.1f}秒)"); return 1
    wav = os.path.join(a.out, "tool_narration.wav"); V.write_wav(wav, master, sr)
    # 場面ごとの画像(beat番号 1〜10 が、台本の2〜11番目に対応。台本の1番目=ロゴ、最後=ツールの詳細の案内)
    images = []; 
    def img(p):
        images.append(os.path.relpath(p, a.out)); return len(images) - 1
    scene_for_beat = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10, 11: 10}
    for bi in range(1, len(beats)):
        fs = sorted(shots[scene_for_beat[bi]])
        if bi == 11: fs = fs[:1]
        w = [1.0] * (len(fs) - 1) + [1.6]; tot = sum(w); acc = 0; fr = []
        for f, ww in zip(fs, w): fr.append({"img": img(f), "at": round(acc / tot, 3)}); acc += ww
        beats[bi]["frames"] = fr
    beats[0]["frames"] = []
    data = {"brand": "BOAT REX PRO", "beats": beats, "images": images, "caster": casters.caster_json(voice.caster)}
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(a.out, "assets"), dirs_exist_ok=True)
    casters.apply_assets(voice.caster, os.path.join(a.out, "assets"))
    html = open(os.path.join(HERE, "tool_short_template.html"), encoding="utf-8").read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    shutil.copyfile(os.path.join(HERE, "tool_short_logo.png"), os.path.join(a.out, "tool_short_logo.png"))
    hp = os.path.join(a.out, "tool_scene.html"); open(hp, "w", encoding="utf-8").write(html)
    stills = [float(x) for x in a.stills.split(",")] if a.stills else None
    mp4 = os.path.join(a.out, f"tool_short_{a.date}.mp4")
    render(hp, total, a.fps, mp4, wav, stills=stills, still_dir=os.path.join(a.out, "stills"))
    credit = voice.caster.get("credit") or voice.caster["voice"]
    mm, dd = int(a.date[4:6]), int(a.date[6:8])
    meta = {"date": a.date, "live": bool(a.live), "key": entry["key"],
            "title": f"【ボートレース解析ツール】{mm}/{dd} {c['venue']}{c['no']}Rの買い目と資金配分|BOAT REX PRO #Shorts",
            "description": (f"BOAT REX PROは、ボートレースの直前情報とオッズから、買い目と資金配分を出す解析ツールです。\n"
                            f"今回は、{c['venue']}ボート{c['no']}レースを、{c['pos']}コース{c['move']}の攻め筋で解析しました。\n\n"
                            f"ツールの詳細、答え合わせ動画は、プロフィール欄のリンクからご覧ください。\n"
                            f"※解析であり、的中や利益を保証するものではありません。舟券の購入は、ご自身の判断でお願いします。\n\n"
                            f"■クレジット\nVOICEVOX:{credit}\n\n#ボートレース #競艇 #BOATREXPRO #Shorts"),
            "tags": ["ボートレース", "競艇", "解析ツール", "買い目", "資金配分", "直前情報", "BOAT REX PRO", "Shorts", c["venue"]]}
    json.dump(meta, open(os.path.join(a.out, "tool_short_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"date": a.date, "content": {k: v for k, v in c.items() if k != "tab"} | {"tab": c["tab"][0]}, "texts": [b["text"] for b in beats],
               "caster": voice.caster["id"], "sec": round(total, 1)}, open(os.path.join(a.out, "tool_short_info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not stills: print(f"[done] {mp4} {os.path.getsize(mp4)/1e6:.1f}MB {total:.1f}秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
