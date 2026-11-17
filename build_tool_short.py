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


def pick_content(date, picks_path, skip=0):
    """毎日違う内容を、日付で決める(同じ日は、何度作っても同じ)。skip は、選べなかったときの次の候補"""
    rnd = random.Random(int(date) * 100 + skip)
    pos = rnd.randint(1, 6)
    move = rnd.choice(MOVES[pos])
    tab = rnd.choice(TC.TABS)
    return {"venue": None, "no": None, "pos": pos, "move": move, "tab": tab, "budget": rnd.choice(BUDGETS)}


def beats_for(c):
    t = c["tab"]
    texts = [None,
             f"注目のレースは、{c['venue']}ボート、{c['no']}レース。",
             "レース場と、レース番号を選択します。",
             "直前情報を読み込んで、",
             "スリット隊形を予想します。",
             f"このレースでは、{c['pos']}コース、{TC.MOVE_SPOKEN.get(c['move'], c['move'])}を選択していきます。",
             f"確率帯は、{t[2]}を狙っていきます。" if t[0] in ("ev", "prob") else f"{t[2]}の帯で、{t[3]}狙っていきます。",
             "解析実行ボタンを押して、",
             "資金配分ボタンを押します。",
             "予算を入力し、オッズを読み込みます。",
             "すぐに、資金配分された買い目が出ます。",
             "ツールの詳細、答え合わせ動画は、プロフィール欄のリンクから。"]
    return texts


def assemble(texts, voice):
    cursor, sr_ref, chunks, beats = 0.0, None, [], []
    for i, tx in enumerate(texts):
        if tx is None:
            beats.append({"text": "", "start": cursor, "dur": LOGO_SEC, "audioLen": 0, "audioOffset": 0, "visemes": []}); cursor += LOGO_SEC; continue
        wav, q = voice.synth(tx)
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
    ap.add_argument("--out", default="out"); ap.add_argument("--stills", default="")
    a = ap.parse_args()
    picks = None
    os.makedirs(a.out, exist_ok=True)
    cap_dir = os.path.join(a.out, "tool_frames")
    shutil.rmtree(cap_dir, ignore_errors=True)
    shots = info = c = None
    for skip in range(8):                                   # 選べない組み合わせだったときは、次の候補(毎回、同じ順で決まる)
        c = pick_content(a.date, picks, skip)
        try:
            shots, info = TC.capture(a.tool, cap_dir, c["venue"], c["no"], c["pos"], c["move"], c["tab"][0], c["budget"], int(a.date) + skip)
            c["venue"], c["no"] = info["venue"], info["no"]
            break
        except RuntimeError as e:
            print(f"::warning::撮影をやり直します({c['venue']}{c['no']}R {c['pos']}コース{c['move']}): {e}")
    if not shots: print("::error::ツールの画面を撮れませんでした"); return 1
    print("[内容]", c["venue"], f"{c['no']}R", f"{c['pos']}コース{c['move']}", c["tab"][0], c["budget"], "円", info)
    voice = V.Voice(a.voice, a.voicevox_url, date=a.date)
    print(f"[caster] {voice.caster['id']}(声: {voice.caster['voice']})")
    total, master, sr, beats = assemble(beats_for(c), voice)
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
    json.dump({"date": a.date, "content": {k: v for k, v in c.items() if k != "tab"} | {"tab": c["tab"][0]}, "texts": [b["text"] for b in beats],
               "caster": voice.caster["id"], "sec": round(total, 1)}, open(os.path.join(a.out, "tool_short_info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not stills: print(f"[done] {mp4} {os.path.getsize(mp4)/1e6:.1f}MB {total:.1f}秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
