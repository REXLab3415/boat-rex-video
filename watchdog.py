# -*- coding: utf-8 -*-
"""
見張り: 「更新・投稿が、止まったまま終わる」ことを無くす。
途中の経過は見ない。「結果(投稿の記録・成功した実行)があるか」だけを、30分おきに見て、足りなければ、その項目を起こし直す。

見る項目(日本時間。D=前日、T=今日):
  1. 答え合わせ動画(D)     0:10〜19:00  uploaded/D.json が無い → 全レース検証(allrace-run-public.yml)を、日付つきで起動
                                          (保存済みなら公式に触らず、動画の材料を置いて、動画づくりを起動する。保存が無ければ、取り直す)
  2. 出走表サイトの更新(T)   7:10〜19:00  6:50以降に成功した毎日の更新(daily-public.yml)が無い → 起動
  1b. 答え合わせショート(D)  0:40〜19:00  動画(D)はあるのに uploaded/D_short.json が無い → short.yml を起動
  3. Instagram(D)           6:10〜20:00  uploaded/D_ig.json か D_ig_thumb.json が無い → instagram-reel.yml を post で起動
  4. Xの投稿文メール(D)      6:10〜12:00  uploaded/D_mail.json が無い(動画の公開から10分以上) → x-mail.yml を起動
  5. 出走表サイトの紹介(T)   10:10〜19:00 uploaded/T_site_ig.json か T_site_mail.json が無い → site-post.yml を起動
  6. 紹介ショート(T)        12:10〜19:00 uploaded/T_newsshort.json が無い → news-short.yml を起動
  7. ツール紹介ショート(T)   15:10〜19:30 uploaded/T_toolshort.json が無い → tool-short.yml を起動

二重起動の防止: 動いている・順番待ち・直近20分以内に起動した実行があれば、起動しない。投稿記録がある項目は、何もしない。
やり直しの上限: 失敗が4回(動画)・3回(そのほか)に達した項目は、起動を止めて、メールで知らせる。
メール: 日本時間 7時台・12時台・19時台の最初の回に、まだ終わっていない主な項目を、1通にまとめて送る(Xのメールは含めない)。
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
REPO = os.environ.get("GITHUB_REPOSITORY", "REXLab3415/boat-rex-video")
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
RECENT_MIN = 20


class Env:
    """GitHubとファイルを触る部分(試験では、これを差し替える)"""

    def __init__(self, now=None):
        self.now = now or datetime.now(JST)
        self._runs = {}

    def rec(self, name):
        p = os.path.join("uploaded", name + ".json")
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def runs(self, wf):
        if wf in self._runs:
            return self._runs[wf]
        out = subprocess.run(
            ["gh", "run", "list", "--repo", REPO, "--workflow", wf, "--limit", "60",
             "--json", "status,conclusion,createdAt,event"],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            raise RuntimeError(f"実行の一覧が読めません: {wf}: {out.stderr.strip()[:200]}")
        self._runs[wf] = json.loads(out.stdout or "[]")
        return self._runs[wf]

    def dispatch(self, wf, inputs):
        cmd = ["gh", "workflow", "run", wf, "--repo", REPO, "--ref", "main"]
        for k, v in inputs.items():
            cmd += ["-f", f"{k}={v}"]
        last = ""
        for n in range(1, 4):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                self._runs.pop(wf, None)
                return True
            last = (r.stderr or r.stdout).strip()[:200]
            print(f"::warning::起動に失敗しました({wf}) {n}/3 {last}")
            if n < 3:
                import time
                time.sleep(20)
        print(f"::error title=起動できません::{wf}: {last}")
        return False


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(JST)


def decide(env):
    """起こすもの(actions)と、まだ終わっていない項目(pending)を返す。実際の起動は、呼び出し側が行う"""
    now = env.now
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    T = now.strftime("%Y%m%d")
    yday = now - timedelta(days=1)
    D = yday.strftime("%Y%m%d")
    Dd = yday.strftime("%Y-%m-%d")

    def inwin(h1, m1, h2, m2=0):
        return day0 + timedelta(hours=h1, minutes=m1) <= now < day0 + timedelta(hours=h2, minutes=m2)

    def busy(wf):
        for r in env.runs(wf):
            if r.get("status") in ACTIVE:
                return True
            if now - parse_ts(r["createdAt"]) < timedelta(minutes=RECENT_MIN):
                return True
        return False

    def fails(wf, since):
        return sum(1 for r in env.runs(wf) if r.get("conclusion") == "failure" and parse_ts(r["createdAt"]) >= since)

    def manual_starts(wf, since):
        return sum(1 for r in env.runs(wf) if r.get("event") == "workflow_dispatch" and parse_ts(r["createdAt"]) >= since)

    actions, pending, notes = [], [], []

    def handle(key, label, report, wfs, since, limit, wf, inputs, ok):
        """ok=True なら終わっている。wfs=動いていたら待つ実行、wf=起こす実行"""
        if ok:
            return
        if report:
            pending.append(f"{label}")
        if any(busy(w) for w in wfs):
            notes.append(f"{key}: 実行中か、起動直後のため、待ちます")
            return
        n = sum(fails(w, since) for w in set(wfs + [wf]))
        if n >= limit:
            notes.append(f"{key}: 失敗が{n}回に達したため、自動の起動は止めます")
            if report:
                pending[-1] += "(自動のやり直しは上限に達しました。人の確認が要ります)"
            return
        actions.append((key, wf, inputs))

    # 1. 答え合わせ動画(前日分)
    if inwin(0, 10, 19):
        handle("video", f"答え合わせ動画({D})が、まだ上がっていません", True,
               ["allrace-run-public.yml", "video.yml"], day0, 4,
               "allrace-run-public.yml", {"date": Dd}, env.rec(D) is not None)

    # 2. 出走表サイトの更新(今日の毎日の更新が、成功したか)
    if inwin(7, 10, 19):
        t0 = day0 + timedelta(hours=6, minutes=50)
        ok = any(r.get("conclusion") == "success" and parse_ts(r["createdAt"]) >= t0 for r in env.runs("daily-public.yml"))
        handle("daily", f"出走表サイトの毎日の更新({T})が、まだ成功していません", True,
               ["daily-public.yml", "allrace-run-public.yml"], t0, 4, "daily-public.yml", {}, ok)

    # 2b. 答え合わせショート(前日分。横動画は上がっているのに、ショートだけ無いとき)
    if inwin(0, 40, 19) and env.rec(D) is not None:
        handle("short", f"答え合わせショート({D})が、まだ上がっていません", True,
               ["short.yml", "video.yml"], day0, 3, "short.yml", {"date": Dd, "voice": "voicevox"},
               env.rec(D + "_short") is not None)

    # 3. Instagram(前日分。ショートができているときだけ)
    if inwin(6, 10, 20) and env.rec(D + "_short") is not None:
        ok = env.rec(D + "_ig") is not None and env.rec(D + "_ig_thumb") is not None
        handle("ig", f"Instagram({D}分)が、まだ投稿されていません", True,
               ["instagram-reel.yml", "video.yml"], day0, 3, "instagram-reel.yml", {"mode": "post", "date": Dd}, ok)

    # 4. Xの投稿文メール(前日分。動画の公開から10分たってから)
    if inwin(6, 10, 12):
        v = env.rec(D)
        ready = v is not None
        if ready and v.get("publishAt"):
            ready = now >= parse_ts(v["publishAt"]) + timedelta(minutes=10)
        if ready and env.rec(D + "_mail") is None and manual_starts("x-mail.yml", day0) < 3:
            handle("xmail", "Xの投稿文メール", False, ["x-mail.yml"], day0, 3, "x-mail.yml", {"date": Dd}, False)

    # 5. 出走表サイトの紹介(今日分)
    if inwin(10, 10, 19):
        ok = env.rec(T + "_site_ig") is not None and env.rec(T + "_site_mail") is not None
        if not ok and manual_starts("site-post.yml", day0) < 3:
            handle("sitepost", f"出走表サイトの紹介({T})が、まだ投稿されていません", True,
                   ["site-post.yml"], day0, 3, "site-post.yml", {}, False)
        elif not ok:
            pending.append(f"出走表サイトの紹介({T})が、まだ投稿されていません(自動のやり直しは上限に達しました)")

    # 6. 紹介ショート(今日分)
    if inwin(12, 10, 19):
        ok = env.rec(T + "_newsshort") is not None
        if not ok and manual_starts("news-short.yml", day0) < 3:
            handle("newsshort", f"出走表サイト紹介ショート({T})が、まだ投稿されていません", True,
                   ["news-short.yml"], day0, 3, "news-short.yml", {"voice": "voicevox"}, False)
        elif not ok:
            pending.append(f"出走表サイト紹介ショート({T})が、まだ投稿されていません(自動のやり直しは上限に達しました)")

    # 7. ツール紹介ショート(今日分)
    if inwin(15, 10, 19, 30):
        ok = env.rec(T + "_toolshort") is not None
        if not ok and manual_starts("tool-short.yml", day0) < 3:
            handle("toolshort", f"ツール紹介ショート({T})が、まだ投稿されていません", True,
                   ["tool-short.yml"], day0, 3, "tool-short.yml", {"voice": "voicevox"}, False)
        elif not ok:
            pending.append(f"ツール紹介ショート({T})が、まだ投稿されていません(自動のやり直しは上限に達しました)")

    return actions, pending, notes


def want_mail(now, pending):
    """7時台・12時台・19時台の最初の回(分が10〜40のとき)だけ、まだ終わっていない項目があれば、メールを送る"""
    return bool(pending) and now.hour in (7, 12, 19) and 10 <= now.minute < 40


def send_mail(pending):
    env = dict(os.environ)
    env["WORKFLOW_NAME"] = "見張り(まだ終わっていない項目があります)"
    env["NOTE"] = "次の項目が、まだ終わっていません。自動で、やり直しています。上限に達した項目は、人の確認が要ります。\n\n" + "\n".join("・" + p for p in pending)
    subprocess.run([sys.executable, "notify_fail.py"], env=env)


def main():
    env = Env()
    print(f"見張り: 日本時間 {env.now.strftime('%Y-%m-%d %H:%M')}")
    try:
        actions, pending, notes = decide(env)
    except Exception as e:
        print(f"::error title=見張りが判断できません::{type(e).__name__}: {str(e)[:200]}")
        return 1
    for n in notes:
        print("::notice::" + n)
    bad = 0
    for key, wf, inputs in actions:
        print(f"::warning::{key}: 終わっていないため、{wf} を起動します {inputs}")
        if not env.dispatch(wf, inputs):
            bad += 1
    if not actions:
        print("::notice::起動するものは、ありません")
    for p in pending:
        print("::notice::未完了: " + p)
    if want_mail(env.now, pending):
        send_mail(pending)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
