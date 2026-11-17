#!/usr/bin/env python3
"""今日の、これから発走するレースを1つ選び、公式サイトから「本物の」直前情報とオッズを取る(ツール紹介ショート用)。
読み取りは、毎晩の全レース検証(allrace_run.py)と同じ関数を、そのまま使う。公式へのアクセスの決まり(3秒あける・403/429で止める)も、同じ official_fetch に従う。
選び方: 今日開催の場を日付で決めた順に見て、場ごとに、結果一覧(resultlist)で終わったレースを調べ、いちばん若い「まだ終わっていない」レースを候補にする。
        そのレースの直前情報(展示タイム)とオッズが、2つとも読み取れたら採用。読み取れない場は飛ばして、次の場へ(最大8場)。
取れなかったら None を返す(仮の値で埋めない)。
"""
import json, os, random, sys
from datetime import datetime, timedelta, timezone

LIVE_DIR8_ORDER = None


def jst_ymd():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")


def pick_live(tool_dir, ymd, seed, log=print, max_venues=8):
    tool_dir = os.path.abspath(tool_dir)
    old = os.getcwd()
    os.chdir(tool_dir)
    sys.path.insert(0, tool_dir)
    try:
        import allrace_run as R   # noqa: E402
        import allrace_probe as P  # noqa: E402
        with open("data/race_card_latest.json", encoding="utf-8") as f:
            card = json.load(f)
        day = card.get(ymd)
        if not day:
            log(f"::error title=今日の出走表がありません::data/race_card_latest.json に {ymd} がありません(今日の出走表は、毎朝7:00ごろ更新されます)")
            return None
        code_name = {c: n for n, c in P.VENUE_CODE.items()}     # 出走表の場は「場コード(01〜24)」で入っている
        venues = [c for c in day.keys() if c in code_name]
        random.Random(seed * 13 + 5).shuffle(venues)
        tried = []
        for jcd in venues[:max_venues]:
            v = code_name[jcd]
            if R.STATE["blocked"]:
                log(f"::warning title=公式サイトへのアクセスを止めました::{R.STATE['blocked']}")
                return None
            html = R.fetch_text(f"{R.BASE}resultlist?hd={ymd}&jcd={jcd}", f"{ymd}_{jcd}_resultlist.html")
            if not html:
                tried.append(f"{v}:結果一覧が取れません"); continue
            done = R.parse_resultlist(html)
            races = day[jcd]
            nxt = [n for n in range(1, 13) if n not in done and str(n) in races]
            if not nxt:
                tried.append(f"{v}:終わっていないレースがありません"); continue
            n = nxt[0]
            bh = R.fetch_text(f"{R.BASE}beforeinfo?rno={n}&jcd={jcd}&hd={ymd}", f"{ymd}_{jcd}_{n:02d}_beforeinfo.html")
            b = R.parse_before(bh) if bh else {"ok": False, "error": "取得できません"}
            if not b.get("ok"):
                tried.append(f"{v}{n}R:直前情報が使えません({b.get('error')})"); continue
            oh = R.fetch_text(f"{R.BASE}odds3t?rno={n}&jcd={jcd}&hd={ymd}", f"{ymd}_{jcd}_{n:02d}_odds3t.html")
            o = R.parse_odds(oh) if oh else {"ok": False, "error": "取得できません"}
            if not o.get("ok"):
                tried.append(f"{v}{n}R:オッズが使えません({o.get('error')})"); continue
            hm = datetime.now(timezone(timedelta(hours=9))).strftime("%H:%M")
            live = {"ok": True, "venue": jcd, "race": str(n), "date": ymd, "at": hm,
                    "beforeinfo": {"ok": True, "ex": b["ex"], "tilt": b["tilt"], "wind": b["wind"], "wave": b["wave"], "windDir8": b.get("wind_dir8")},
                    "odds": {"ok": True, "count": len(o["odds"]), "odds": o["odds"]}}
            log(f"[本物のデータ] {v} {n}R(結果が出ている: {sorted(done)}) 直前情報・オッズとも読み取れました")
            return {"venue": v, "no": n, "live": live}
        log("::error title=本物のデータで撮れるレースがありません::" + " / ".join(tried or ["今日開催の場がありません"]))
        return None
    finally:
        os.chdir(old)
