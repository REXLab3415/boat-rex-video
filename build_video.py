#!/usr/bin/env python3
"""BOAT SCENARIO PRO 答え合わせ動画 - 試験版ビルダー

流れ: data/raw の実結果 → ダミー予想(SAMPLE) → 台本 → 音声(VOICEVOX) → 口パク用タイムライン
      → HTMLを1フレームずつキャプチャ(Playwright) → ffmpegでmp4化

使い方(GitHub Actions内):
  python video_test/build_video.py --date 20261029 --voice voicevox
ローカル確認(VOICEVOXなし・ダミー音声):
  python video_test/build_video.py --date 20261029 --voice dummy
"""
import argparse
import collections
import gzip
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SPEAKER_NAME = "青山龍星"
LEAD = 0.35          # ビート開始から音声開始までの間
TAIL = 0.7           # 音声終了からビート終了までの間
MIN_DUR = {"opening": 4.5, "card": 5.0, "result": 5.5, "payout": 6.0, "graph": 7.5, "ending": 4.0}


# ------------------------------------------------------------------ data
def load_day(root, date):
    path = os.path.join(root, "data", "raw", f"{date}.json.gz")
    if not os.path.exists(path):
        sys.exit(f"データがありません: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def group_races(rows, venue):
    by = collections.defaultdict(list)
    for r in rows:
        if r["venue"] == venue:
            by[int(r["race_no"])].append(r)
    return by


def dummy_picks(entries):
    """ダミー予想: 展示タイム順+枠補正の重みで、3連単の上位8点を出す(ツール本体の計算ではない)。"""
    base = [5.0, 3.5, 2.4, 1.5, 1.0, 0.7]
    ranked = sorted(entries, key=lambda e: (e["tenji"] if e["tenji"] is not None else 99, e["boat"]))
    w = {}
    for i, e in enumerate(ranked):
        w[e["boat"]] = base[i] * (1.8 if e["boat"] == 1 else 1.0)
    boats = list(w)
    S = sum(w.values())
    combos = []
    for a in boats:
        for b in boats:
            if b == a:
                continue
            for c in boats:
                if c in (a, b):
                    continue
                p = w[a] / S * w[b] / (S - w[a]) * w[c] / (S - w[a] - w[b])
                combos.append((p, f"{a}-{b}-{c}"))
    combos.sort(reverse=True)
    marks = [e["boat"] for e in sorted(entries, key=lambda e: -w[e["boat"]])][:4]
    return [c[1] for c in combos[:8]], marks


def build_race(no, rows):
    r0 = rows[0]
    entries = []
    for r in sorted(rows, key=lambda r: r["boat"]):
        entries.append({
            "boat": int(r["boat"]), "toban": r.get("toban"), "tenji": r.get("tenji"),
            "course": r.get("course"), "st": r.get("start_timing"), "flag": r.get("start_flag"),
            "time": r.get("race_time"), "chaku": r.get("chaku"),
        })
    picks, marks = dummy_picks(entries)
    order = sorted(entries, key=lambda e: (e["chaku"] if isinstance(e["chaku"], int) else 99, e["boat"]))
    wd, ws = r0.get("wind_dir") or "-", r0.get("wind_speed_m")
    wave_cm = r0.get("wave_cm")
    tri = r0["trifecta"]
    return {
        "no": no, "entries": entries, "order": order, "marksOrder": marks, "picks": picks,
        "tri": tri, "pay": int(r0["trifecta_pay"]), "pop": int(r0["trifecta_pop"]),
        "kimarite": r0.get("kimarite") or "", "hit": tri in picks,
        "wind": f"{wd} {ws:g}m" if ws is not None else wd,
        "wave": f"{wave_cm:g}cm" if wave_cm is not None else "-",
    }


def choose_races(by, races_arg):
    allr = {n: build_race(n, rs) for n, rs in by.items() if len(rs) == 6 and rs[0].get("trifecta")}
    if races_arg:
        nums = [int(x) for x in races_arg.split(",")]
        return [allr[n] for n in nums], allr
    hits = sorted([r for r in allr.values() if r["hit"]], key=lambda r: r["pay"])
    miss = sorted([r for r in allr.values() if not r["hit"]], key=lambda r: r["pay"])
    chosen = []
    if hits:
        chosen.append(hits[0])                      # 的中のうち、配当が最も低いレース
    if miss:
        chosen.append(miss[len(miss) // 2])         # 不的中の中央値付近
    rest = [r for r in sorted(allr.values(), key=lambda r: -r["pay"]) if r not in chosen]
    if rest:
        chosen.append(rest[0])                      # 残りのうち最高配当(荒れたレース)
    chosen = sorted(chosen[:3], key=lambda r: r["no"])
    return chosen, allr


# ------------------------------------------------------------------ voice
class Voice:
    def __init__(self, mode, url, audible=False, bad_query=False):
        self.mode, self.url = mode, url.rstrip("/")
        self.audible, self.bad_query = audible, bad_query      # 動作確認用の仮の設定(通常は使わない)
        self.speaker = None
        if mode == "voicevox":
            self.speaker = self._resolve_speaker()
            print(f"[voice] VOICEVOX speaker id = {self.speaker}")
            self._register_dict()

    def _get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else b""
        req = urllib.request.Request(self.url + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()

    def _register_dict(self):
        """user_dict.json の言葉を辞書に登録する(エンジンは毎回まっさらで立ち上がるため、実行のたびに入れ直す)。
        失敗しても動画は作る。登録できなかった言葉は、実行の黄色い警告に出す。"""
        path = os.path.join(HERE, "user_dict.json")
        if not os.path.exists(path):
            print("[dict] user_dict.json がありません(辞書なしで続けます)")
            return
        with open(path, encoding="utf-8") as f:
            words = json.load(f)
        bad = []
        for w in words:
            try:
                qs = urllib.parse.urlencode({"surface": w["surface"], "pronunciation": w["pronunciation"],
                                             "accent_type": str(w.get("accent_type", 0)), "priority": "10"})
                req = urllib.request.Request(self.url + "/user_dict_word?" + qs, data=b"", method="POST")
                urllib.request.urlopen(req, timeout=60).read()
            except Exception as e:
                bad.append(f"{w['surface']}(登録失敗: {e})")
                continue
            # 本当に効いたかを確かめる(読みがカナで返る)
            try:
                q = json.loads(self._post(f"/audio_query?text={urllib.parse.quote(w['surface'])}&speaker={self.speaker}"))
                kana = re.sub(r"[' /_、]", "", q.get("kana", ""))
                if w["pronunciation"] not in kana:
                    bad.append(f"{w['surface']}(読みが {kana} のまま)")
                else:
                    print(f"[dict] {w['surface']} → {kana} OK")
            except Exception as e:
                bad.append(f"{w['surface']}(確認に失敗: {e})")
        if bad:
            msg = "、".join(bad)
            print(f"[dict] 登録できなかった言葉: {msg}")
            print(f"::warning title=辞書に登録できない言葉があります::{msg}", flush=True)
        else:
            print(f"[dict] {len(words)}語を登録しました")

    def _resolve_speaker(self):
        sp = self._get("/speakers")
        for s in sp:
            if s["name"] == SPEAKER_NAME:
                for st in s["styles"]:
                    if st["name"] == "ノーマル":
                        return st["id"]
                return s["styles"][0]["id"]
        names = [s["name"] for s in sp]
        sys.exit(f"話者 {SPEAKER_NAME} が見つかりません。利用可能: {names}")

    def synth(self, text):
        """return (wav_bytes, query_dict)"""
        if self.mode == "voicevox":
            q = json.loads(self._post(f"/audio_query?text={urllib.parse.quote(text)}&speaker={self.speaker}"))
            q["speedScale"] = 1.05
            q["prePhonemeLength"] = 0.05
            q["postPhonemeLength"] = 0.12
            wav = self._post(f"/synthesis?speaker={self.speaker}", q)
            if self.bad_query:
                q = dict(q, accent_phrases=[])            # 計画表が使えない状況を再現(確認用)
            return wav, q
        wav, q = dummy_synth(text, amp=0.35 if self.audible else 0.0)
        if self.bad_query:
            q = dict(q, accent_phrases=[])
        return wav, q


def dummy_synth(text, sr=24000, amp=0.0):
    """VOICEVOXなしの確認用。文字数から疑似モーラ列を作り、ブザー音で音声にする(映像の同期確認専用)。"""
    rnd = random.Random(sum(map(ord, text)))
    moras, phrase = [], []
    for ch in text:
        if ch in "、。":
            if phrase:
                moras.append(("phrase", phrase)); phrase = []
            moras.append(("pause", 0.28 if ch == "。" else 0.18))
        elif ch.strip():
            phrase.append({"vowel": rnd.choice("aiueo"), "consonant": rnd.choice([None, "k", "s", "t", "m", "n", "r"]),
                           "consonant_length": 0.05, "vowel_length": 0.085})
    if phrase:
        moras.append(("phrase", phrase))
    aps = []
    for kind, v in moras:
        if kind == "phrase":
            aps.append({"moras": v, "pause_mora": None})
        elif aps:
            aps[-1]["pause_mora"] = {"vowel": "pau", "vowel_length": v, "consonant": None, "consonant_length": None}
    q = {"accent_phrases": aps, "speedScale": 1.0, "prePhonemeLength": 0.05, "postPhonemeLength": 0.12}
    # 音声合成
    pcs, t_total = [], q["prePhonemeLength"]
    segs = [(0.0, t_total, None)]
    for ap in aps:
        for m in ap["moras"]:
            d = (m["consonant_length"] or 0) + m["vowel_length"]
            segs.append((t_total, t_total + d, m["vowel"])); t_total += d
        if ap["pause_mora"]:
            d = ap["pause_mora"]["vowel_length"]; segs.append((t_total, t_total + d, None)); t_total += d
    t_total += q["postPhonemeLength"]
    n = int(t_total * sr)
    x = np.zeros(n, dtype=np.float64)
    f1 = {"a": 800, "i": 300, "u": 350, "e": 500, "o": 450}
    for s, e, v in segs:
        if v is None:
            continue
        i0, i1 = int(s * sr), min(n, int(e * sr))
        tt = np.arange(i1 - i0) / sr
        env = np.sin(np.pi * np.linspace(0, 1, i1 - i0)) ** 0.6
        x[i0:i1] = env * (0.5 * np.sin(2 * np.pi * 130 * tt) + 0.25 * np.sin(2 * np.pi * f1[v] * tt) * np.sin(2 * np.pi * 130 * tt))
    x = (x * amp * 32767).astype(np.int16)      # 既定は無音(映像確認用。口パクのタイミングだけ作る)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
    return buf.getvalue(), q


def read_wav(b):
    with wave.open(io.BytesIO(b), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    assert sw == 2, "16bit以外のwavは未対応"
    a = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1).astype(np.int16)
    return a, sr


VIS = {"a": "a", "A": "a", "i": "i", "I": "i", "u": "u", "U": "u", "e": "e", "E": "e", "o": "o", "O": "o"}
BILABIAL = {"m", "b", "p", "my", "by", "py"}


def visemes_from_query(q, wav_len):
    """audio_queryのモーラ(母音+長さ)から、[開始秒, 終了秒, 口の形] の列を作る。実際のwav長に合わせて伸縮する。"""
    t = q.get("prePhonemeLength", 0.0)
    segs = []
    for ap in q["accent_phrases"]:
        for m in ap["moras"]:
            cl = m.get("consonant_length") or 0.0
            vl = m.get("vowel_length") or 0.0
            v = m.get("vowel")
            if cl > 0 and m.get("consonant") in BILABIAL:
                segs.append([t, t + cl, "closed"]); t += cl; cl = 0.0
            if v == "cl":
                segs.append([t, t + cl + vl, "closed"])
            elif v == "N":
                segs.append([t, t + cl + vl, "u"])
            else:
                segs.append([t, t + cl + vl, VIS.get(v, "e")])
            t += cl + vl
        if ap.get("pause_mora"):
            pl = ap["pause_mora"]["vowel_length"]
            segs.append([t, t + pl, "closed"]); t += pl
    total = t + q.get("postPhonemeLength", 0.0)
    scale = wav_len / total if total > 0 else 1.0
    return [[round(s * scale, 3), round(e * scale, 3), sh] for s, e, sh in segs]


def visemes_from_audio(a, sr, wav_len, fps=60):
    """保険: 計画表が使えないとき、音声の音量の波形から口を動かす(母音ごとの形は出ない)。声が大きいところで開き、静かなところで閉じる。"""
    x = a.astype(np.float64) / 32768.0
    hop = max(1, int(sr / fps)); n = len(x) // hop
    if n == 0:
        return []
    env = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1))
    env = np.convolve(env, np.ones(3) / 3, "same")
    peak = float(np.percentile(env, 98))
    if peak < 1e-4:
        return []                                   # 無音
    e = env / peak
    segs, active = [], False
    for i, v in enumerate(e):                       # 開く/閉じるのしきい値を分けて、ばたつきを防ぐ
        t = i / fps
        if not active and v > 0.12:
            active, s, pk = True, t, v
        elif active:
            pk = max(pk, v)
            if v < 0.07:
                segs.append((s, t, pk)); active = False
    if active:
        segs.append((s, n / fps, pk))
    out, cyc = [], 0
    for s, t, pk in segs:                           # 長い塊は約0.26秒ごとに開閉を繰り返す
        cur = s
        while cur < t - 0.05:
            end = min(cur + 0.26, t)
            shape = (["a", "o"] if pk > 0.55 else ["e", "u"])[cyc % 2]; cyc += 1
            out.append([round(cur, 3), round(end, 3), shape]); cur = end
    return out


def pick_visemes(q, a, sr, alen, label):
    """通常は計画表(母音+長さ)から。使えなければ音量方式に切り替えて、動画は必ず作る。戻り値: (口の形の列, 方式)"""
    try:
        vis = visemes_from_query(q, alen)
        voiced = sum(v[1] - v[0] for v in vis if v[2] != "closed")
        if voiced >= 0.1 * alen:
            return vis, "mora"
        reason = "計画表から口の形がほとんど取れませんでした"
    except Exception as ex:                         # 想定外の形式でも止めない
        reason = f"計画表の読み取りに失敗しました ({type(ex).__name__}: {ex})"
    vis = visemes_from_audio(a, sr, alen)
    method = "audio" if vis else "none"
    msg = f"[{label}] {reason}。" + ("音量の波形で口を動かします(母音の形は出ません)" if vis else "音声も無音のため、口は動きません")
    print(f"[lipsync] {msg}", flush=True)
    return vis, method


# ------------------------------------------------------------------ script & timeline
def say_boat(n):
    return f"{n}号艇"


def build_script(date, venue, races, graph, brand_reading="ボートレックスプロ"):
    y, m, d = int(date[:4]), int(date[4:6]), int(date[6:])
    beats = [{"type": "opening",
              "text": f"{m}月{d}日、ボートレース解析ツール、{brand_reading}答え合わせの時間です。"}]
    for r in races:
        mk = r["marksOrder"]
        t_card = f"{r['no']}レース。ツールの本命は{say_boat(mk[0])}、対抗は{say_boat(mk[1])}、三番手は{say_boat(mk[2])}。"
        o = r["order"]
        km = f"きまりては、{r['kimarite']}でした。" if r["kimarite"] else ""   # 「決まり手」は「きまりしゅ」と読まれるため、ひらがなで書く
        t_res = f"結果です。1着、{say_boat(o[0]['boat'])}。2着、{say_boat(o[1]['boat'])}。3着、{say_boat(o[2]['boat'])}。{km}"
        a, b, c = r["tri"].split("-")
        verdict = "ツールの買い目に含まれていて、的中です。" if r["hit"] else "ツールの買い目には含まれず、不的中でした。"
        t_pay = f"3連単は、{a}、{b}、{c}。払戻金は{r['pay']}円、{r['pop']}番人気。{verdict}"
        beats += [{"type": "card", "race": r, "text": t_card},
                  {"type": "result", "race": r, "text": t_res},
                  {"type": "payout", "race": r, "text": t_pay}]
    beats.append({"type": "graph", "text": f"今月の累計回収率の推移です。現在は、{graph['values'][-1]:.0f}パーセント。こちらもサンプルの数値です。"})
    beats.append({"type": "ending", "text": f"{brand_reading}についての詳細は動画概要欄をご覧ください。ではまた明日お会いしましょう。"})
    return beats


def make_graph(date):
    rnd = random.Random(int(date))
    n = max(5, int(date[6:]))
    v, vals = 100.0, []
    for _ in range(n):
        v = min(140.0, max(70.0, v + 0.08 * (106.0 - v) + rnd.gauss(0, 4.0))); vals.append(round(v, 1))
    return {"days": [f"{i + 1}" for i in range(n)], "values": vals, "label": f"{int(date[4:6])}月 累計回収率(SAMPLE)"}


def assemble(beats, voice, last_tail=1.4):
    cursor, sr_ref, chunks = 0.0, None, []
    for i, b in enumerate(beats):
        wav, q = voice.synth(b["text"])
        a, sr = read_wav(wav)
        sr_ref = sr_ref or sr
        assert sr == sr_ref
        alen = len(a) / sr
        b["audioLen"] = round(alen, 3)
        b["audioOffset"] = LEAD
        b["visemes"], b["lipsync"] = pick_visemes(q, a, sr, alen, f'{i + 1}番目 {b["type"]}')
        tail = last_tail if i == len(beats) - 1 else TAIL
        b["dur"] = round(max(MIN_DUR[b["type"]], LEAD + alen + tail), 3)
        b["start"] = round(cursor, 3)
        chunks.append((cursor + LEAD, a))
        # 演出のタイミング(音声の進み具合に合わせる)
        t0 = LEAD
        if b["type"] == "card":
            b["markTimes"] = [t0 + alen * f for f in (0.50, 0.68, 0.86, 0.95)]
        elif b["type"] == "result":
            f = (0.16, 0.34, 0.52)
            b["ordTimes"] = [t0 + alen * f[0], t0 + alen * f[1], t0 + alen * f[2]] + [t0 + alen * 0.60 + 0.12 * k for k in range(3)]
            b["kmTime"] = t0 + alen * 0.80
        elif b["type"] == "payout":
            b["stampTime"] = t0 + alen * 0.84
        cursor += b["dur"]
    total = cursor
    master = np.zeros(int(total * sr_ref) + sr_ref, dtype=np.int16)
    for off, a in chunks:
        i0 = int(off * sr_ref)
        master[i0:i0 + len(a)] = a
    return total, master, sr_ref


def write_wav(path, a, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(a.tobytes())


# ------------------------------------------------------------------ render
def render(html_path, total, fps, width, height, out_mp4, audio_path, stills=None, still_dir=None, max_sec=None):
    from playwright.sync_api import sync_playwright
    scale = width / 1920.0
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--font-render-hinting=none"])
        pg = br.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=scale)
        pg.goto("file://" + os.path.abspath(html_path))
        pg.wait_for_timeout(400)
        if stills:
            os.makedirs(still_dir, exist_ok=True)
            for s in stills:
                pg.evaluate(f"render({s})")
                pg.screenshot(path=os.path.join(still_dir, f"still_{s:06.2f}.png"))
            br.close()
            return
        dur = min(total, max_sec) if max_sec else total
        n = int(math.ceil(dur * fps))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
               "-i", audio_path, "-t", f"{dur:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
               "-r", str(fps), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4]
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(n):
            pg.evaluate(f"render({i / fps:.4f})")
            ff.stdin.write(pg.screenshot(type="jpeg", quality=90))
            if i % 150 == 0:
                print(f"[render] {i}/{n} frames", flush=True)
        ff.stdin.close()
        rc = ff.wait()
        br.close()
        if rc != 0:
            sys.exit(f"ffmpeg失敗 (exit {rc})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20261029")
    ap.add_argument("--venue", default="", help="空欄なら、その日のデータで最初の場")
    ap.add_argument("--races", default="", help="例: 1,7,12  空欄なら自動(的中・不的中・荒れたレースを1本ずつ)")
    ap.add_argument("--voice", choices=["voicevox", "dummy"], default="voicevox")
    ap.add_argument("--dummy-audible", action="store_true", help="確認用: dummy音声に仮の音を入れる(通常は無音)")
    ap.add_argument("--simulate-bad-query", action="store_true", help="確認用: 計画表が使えない状況を再現する")
    ap.add_argument("--voicevox-url", default="http://127.0.0.1:50021")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--brand", default="BOAT REX PRO", help="動画に表示するツール名(サイトの表記に合わせる)")
    ap.add_argument("--brand-reading", default="ボートレックスプロ", help="ナレーションでの読み")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--stills", default="", help="例: 3,12.5 指定時刻の静止画だけ出力して終了")
    ap.add_argument("--max-sec", type=float, default=0)
    args = ap.parse_args()

    root = os.path.abspath(os.path.join(HERE, ".."))
    os.makedirs(args.out, exist_ok=True)
    rows = load_day(root, args.date)
    venue = args.venue or rows[0]["venue"]
    by = group_races(rows, venue)
    races, allr = choose_races(by, args.races)
    print(f"[data] {args.date} {venue} races={[r['no'] for r in races]} hit={[r['hit'] for r in races]}")

    graph = make_graph(args.date)
    beats = build_script(args.date, venue, races, graph, args.brand_reading)
    voice = Voice(args.voice, args.voicevox_url, args.dummy_audible, args.simulate_bad_query)
    total, master, sr = assemble(beats, voice)
    cnt = collections.Counter(b["lipsync"] for b in beats)
    label = {"mora": "通常(VOICEVOXの計画表)", "audio": "音量の波形(保険)", "none": "動かない(無音)"}
    summary = "口パクの方式: " + " / ".join(f"{label[k]} {v}か所" for k, v in cnt.items())
    print(f"[lipsync] {summary}")
    if set(cnt) != {"mora"}:                       # 警告は1本にまとめる(Actionsの画面に黄色で出る)
        print(f"::warning title=口パクの方式を切り替えました::{summary}。VOICEVOXの計画表が使えなかった場面があります。ログの[lipsync]行を確認してください", flush=True)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(f"### 口パク\n{summary}\n" + ("\n⚠ 通常の方式以外の場面があります。ログの黄色い警告を確認してください。\n" if set(cnt) != {"mora"} else ""))
    audio_path = os.path.join(args.out, "narration.wav")
    write_wav(audio_path, master, sr)

    y, m, d = int(args.date[:4]), int(args.date[4:6]), int(args.date[6:])
    data = {
        "date": args.date, "dateLabel": f"{y}年{m}月{d}日", "venue": venue,
        "nraces": len(allr), "shown": len(races), "beats": beats, "graph": graph,
        "ticker": [f"{venue} {n}R <b>{r['tri']}</b> ¥{r['pay']:,}" for n, r in sorted(allr.items())],
    }
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(HERE, "assets", "caster.json"), encoding="utf-8") as f:
        data["caster"] = json.load(f)
    with open(os.path.join(HERE, "assets", "layout.json"), encoding="utf-8") as f:
        data["layout"] = json.load(f)
    with open(os.path.join(HERE, "signboard.txt"), encoding="utf-8") as f:
        data["sign"] = [ln.strip() for ln in f if ln.strip()]
    data["brand"] = args.brand
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(args.out, "assets"), dirs_exist_ok=True)
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    html_path = os.path.join(args.out, "scene.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(args.out, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"[timeline] total {total:.1f}s  beats={[(b['type'], b['dur']) for b in beats]}")

    stills = [float(x) for x in args.stills.split(",")] if args.stills else None
    out_mp4 = os.path.join(args.out, f"boat_check_{args.date}.mp4")
    height = int(round(args.width * 9 / 16))
    render(html_path, total, args.fps, args.width, height, out_mp4, audio_path,
           stills=stills, still_dir=os.path.join(args.out, "stills"), max_sec=args.max_sec or None)
    if not stills:
        print(f"[done] {out_mp4}  ({os.path.getsize(out_mp4) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
