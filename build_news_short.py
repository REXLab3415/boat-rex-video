#!/usr/bin/env python3
"""BOAT REX PRO オリジナル出走表の紹介ショート(縦1080x1920)ビルダー ※公開リポジトリ(boat-rex-video)用
流れ: 出走表サイトの画面を撮る(news_capture.py。グレードが一番高い場の最終レース) → 台本(日付で日替わり) → 声(キャスター4人ローテ・口パクつき) → 動画(mp4)
台本: ①○月○日の注目レース ②ごらんのメンバー ③場の話(4種から1つ) ④固定(1号艇・2号艇の BOAT REX PRO データ) ⑤選手の話(6種から1つ) ⑥プロフィール欄のリンクへ
数字は読まない(画面に出す)。長さの上限は付けない(YouTube公式: 縦長のショートは3分まで)。
使い方: python build_news_short.py --date 20261118 --base https://boat-rex-pro.com/ --voice voicevox|dummy --out out --live
"""
import argparse, glob, json, os, random, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_video as V  # noqa: E402
import build_tool_short as BT  # noqa: E402   (声・口パク・動画の書き出しの部品を、そのまま使う)
import casters  # noqa: E402
import news_capture as NC  # noqa: E402

HARD_MAX_SEC = 175.0       # YouTubeのショートは3分まで。余裕を見た安全の線(これを超えたら投稿しない)
BASE_DEFAULT = "https://boat-rex-pro.com/"

# 場の話(4種) key: (読ませる文, 画面に出す文, 画像の名前)
VENUE_TOPICS = {
    "fx": ("この場の特徴が、文章で説明されています。", "この場の特徴が、文章で説明されています。", "venue_fx"),
    "pc": ("この場の、コース別の1着率が、過去1年分でわかります。", "この場の、コース別の1着率が、過去1年分でわかります。", "venue_pc"),
    "pk": ("この場で多い決まり手が、ランキングでわかります。", "この場で多い決まり手が、ランキングでわかります。", "venue_pk"),
    "pd": ("この場で出やすい3連単の出目と、平均配当がわかります。", "この場で出やすい3連単の出目と、平均配当がわかります。", "venue_pd"),
}
# 選手の話(6種)。rank / st は、その日のそのレースに、バッジが1人でもいるときだけ使う
PLAYER_TOPICS = {
    "rank": ("選手には、勝率のランクがつきます。エスエスエスは、勝率1位から10位です。", "選手には、勝率のランクがつきます。SSSは、勝率1位から10位です。", "p_rank"),
    "st": ("スタートの速さも、ランクでわかります。", "スタートの速さも、ランクでわかります。", "p_st"),
    "waku": ("その選手が、この枠番で走ったときの成績が、全国とこの場の両方でわかります。", "その選手が、この枠番で走ったときの成績が、全国とこの場の両方でわかります。", "p_waku"),
    "motor": ("モーターとボートの、今節の順位と気配がわかります。", "モーターとボートの、今節の順位と気配がわかります。", "p_motor"),
    "r10": ("この枠番での、直近10走の、進入、スタート、着順がわかります。", "この枠番での、直近10走の、進入、スタート、着順がわかります。", "p_r10"),
    "nige2": ("1号艇が逃げた時に、2着になりやすい艇もわかります。", "1号艇が逃げた時に、2着になりやすい艇もわかります。", "p_nige2"),
}
LINE4 = "1号艇には、逃げ率、差され率、まくられ率。2号艇には、逃がし率が出ます。"
LINE6_SPOKEN = "ボートレックスプロ、オリジナル出走表は、プロフィール欄のリンクから。"
LINE6_SHOWN = "BOAT REX PRO オリジナル出走表は、プロフィール欄のリンクから。"


def recent_keys(date):
    """直近に投稿した日の、場の話・選手の話(同じ題材が続かないようにする)。前の日のものを返す"""
    best = None
    for p in glob.glob(os.path.join(HERE, "uploaded", "*_newsshort.json")):
        d = os.path.basename(p)[:8]
        if d.isdigit() and int(d) < int(date) and (best is None or int(d) > best[0]):
            try:
                k = json.load(open(p, encoding="utf-8")).get("key", "")
                if "|" in k: best = (int(d), k.split("|"))
            except Exception: pass
    return best[1] if best else []


def pick_topics(date, info):
    rnd = random.Random(int(date) * 41 + 9)
    prev = recent_keys(date)
    vt = [k for k in VENUE_TOPICS if k not in prev[:1]] or list(VENUE_TOPICS)
    pt = [k for k in PLAYER_TOPICS if k not in prev[1:2]]
    if not info.get("has_rk"): pt = [k for k in pt if k != "rank"]
    if not info.get("has_sc"): pt = [k for k in pt if k != "st"]
    if not pt: pt = ["waku", "motor", "r10", "nige2"]
    return rnd.choice(vt), rnd.choice(pt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True); ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--voice", choices=["voicevox", "dummy"], default="voicevox"); ap.add_argument("--voicevox-url", default="http://127.0.0.1:50021")
    ap.add_argument("--fps", type=int, default=30); ap.add_argument("--out", default="out"); ap.add_argument("--stills", default="")
    ap.add_argument("--live", action="store_true", help="本番(今日の出走表を撮る)。なしは、動作確認用")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.live:
        import tool_live as TL
        ymd = TL.jst_ymd()
        if a.date != ymd and os.environ.get("ALLOW_OLD_DATE") != "1":
            print(f"::error::撮れるのは、日本時間の今日({ymd})の出走表だけです(指定: {a.date})"); return 1
    cap_dir = os.path.join(a.out, "news_frames"); shutil.rmtree(cap_dir, ignore_errors=True)
    try:
        shots, info = NC.capture(a.base, cap_dir, a.date, int(a.date), check_date=(os.environ.get("SKIP_DATE_CHECK") != "1"))
    except Exception as e:
        print(f"::error title=出走表サイトの画面を撮れませんでした::{e}"); return 1
    t4, t5 = pick_topics(a.date, info)
    mm, dd = int(a.date[4:6]), int(a.date[6:8]); v, n = info["venue"], info["no"]
    line1 = f"{mm}月{dd}日の注目レース。{v}ボート、{n}レース。"
    line2 = "ごらんのメンバーで行われます。"
    # 台本 = [ロゴ, ①〜⑥]。読ませる文(spoken)と、画面に出す文(shown)は、別に持つ(エスエスエス・ボートレックスプロの読みのため)
    spoken = [None, line1, line2, VENUE_TOPICS[t4][0], LINE4, PLAYER_TOPICS[t5][0], LINE6_SPOKEN]
    shown = [None, line1, line2, VENUE_TOPICS[t4][1], LINE4, PLAYER_TOPICS[t5][1], LINE6_SHOWN]
    print(f"[内容] {v} {n}R({info['grade'] or 'グレードなし'}) / 場の話={t4} / 選手の話={t5}")
    voice = V.Voice(a.voice, a.voicevox_url, date=a.date)
    print(f"[caster] {voice.caster['id']}(声: {voice.caster['voice']})")
    total, master, sr, beats = BT.assemble(spoken, voice, float(os.environ.get("INTO_GAIN") or 1.0) if os.environ.get("MATCH_AOYAMA", "1") == "1" else 0.0)
    for b, s in zip(beats, shown):
        if s: b["text"] = s
    print(f"[長さ] {total:.1f}秒")
    if total > HARD_MAX_SEC: print(f"::error::{HARD_MAX_SEC:.0f}秒を超えました({total:.1f}秒)。YouTubeのショートは3分まで"); return 1
    wav = os.path.join(a.out, "news_narration.wav"); V.write_wav(wav, master, sr)
    # 場面ごとの画像(beat 1〜6 = 台本の①〜⑥)。at = その場面の中で、画像が切り替わる位置(0〜1)
    images = []
    def img(k):
        images.append(os.path.relpath(shots[k], a.out)); return len(images) - 1
    plan = {1: [("top", 0.0), ("grid", 0.45)], 2: [("members", 0.0)], 3: [(VENUE_TOPICS[t4][2], 0.0)],
            4: [("kg_1", 0.0), ("kg_12", 0.5)], 5: [(PLAYER_TOPICS[t5][2], 0.0)], 6: [("grid", 0.0)]}
    for bi in range(1, len(beats)):
        beats[bi]["frames"] = [{"img": img(k), "at": at} for k, at in plan[bi]]
    beats[0]["frames"] = []
    data = {"brand": "BOAT REX PRO", "beats": beats, "images": images, "caster": casters.caster_json(voice.caster)}
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(a.out, "assets"), dirs_exist_ok=True)
    casters.apply_assets(voice.caster, os.path.join(a.out, "assets"))
    html = open(os.path.join(HERE, "news_short_template.html"), encoding="utf-8").read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    shutil.copyfile(os.path.join(HERE, "news_short_logo.png"), os.path.join(a.out, "news_short_logo.png"))
    hp = os.path.join(a.out, "news_scene.html"); open(hp, "w", encoding="utf-8").write(html)
    stills = [float(x) for x in a.stills.split(",")] if a.stills else None
    mp4 = os.path.join(a.out, f"news_short_{a.date}.mp4")
    BT.render(hp, total, a.fps, mp4, wav, stills=stills, still_dir=os.path.join(a.out, "stills"))
    credit = voice.caster.get("credit") or voice.caster["voice"]
    meta = {"date": a.date, "live": bool(a.live), "key": f"{t4}|{t5}", "venue": v, "no": n,
            "title": f"【ボートレース】{mm}/{dd} {v}{n}Rの出走表|BOAT REX PRO オリジナル出走表 #Shorts",
            "description": (f"BOAT REX PRO オリジナル出走表は、レース場の特徴や、選手の独自ランクなど、公式の出走表にはない情報を載せた、ボートレース(競艇)の出走表です。\n"
                            f"今回は、{v}ボート{n}レースの出走表を紹介しました。\n\n"
                            f"オリジナル出走表は、プロフィール欄のリンクからご覧ください。\n"
                            f"※掲載している買い目は、的中や利益を保証するものではありません。舟券の購入は、ご自身の判断でお願いします。\n\n"
                            f"■クレジット\nVOICEVOX:{credit}\n\n#ボートレース #競艇 #BOATREXPRO #Shorts"),
            "tags": ["ボートレース", "競艇", "出走表", "オリジナル出走表", "BOAT REX PRO", "Shorts", v]}
    json.dump(meta, open(os.path.join(a.out, "news_short_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"date": a.date, "venue": v, "no": n, "grade": info["grade"], "topics": [t4, t5], "texts": [b["text"] for b in beats],
               "caster": voice.caster["id"], "sec": round(total, 1)}, open(os.path.join(a.out, "news_short_info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not stills: print(f"[done] {mp4} {os.path.getsize(mp4)/1e6:.1f}MB {total:.1f}秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
