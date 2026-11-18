#!/usr/bin/env python3
"""out/ にできた出走表サイト紹介ショート(news_short_日付.mp4)を、YouTubeに投稿する。
  - 同じ日をすでに投稿していたら(uploaded/日付_newsshort.json がある)、飛ばす。--force で上げ直す。
  - 公開の設定と、夜に動いたときの朝6:00予約公開は、ほかの動画と同じ(youtube_privacy.txt。いまは public)。
  - 鍵は環境変数 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN(ほかの動画と同じ)。投稿の部品は upload_youtube.py をそのまま使う。
"""
import argparse, json, os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import upload_youtube as U  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True); ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    mp4 = os.path.join(a.out, f"news_short_{a.date}.mp4")
    rec = os.path.join(HERE, "uploaded", f"{a.date}_newsshort.json")
    if os.path.exists(rec) and not a.force:
        print(f"::notice::{a.date} の出走表サイト紹介ショートはすでに投稿済みです"); return 0
    if not os.path.exists(mp4):
        print("::error title=出走表サイト紹介ショートを投稿できません::動画がありません。投稿しません"); return 1
    mp = os.path.join(a.out, "news_short_meta.json")
    if not os.path.exists(mp):
        print("::error title=出走表サイト紹介ショートを投稿できません::news_short_meta.json がありません"); return 1
    meta = json.load(open(mp, encoding="utf-8"))
    if meta.get("date") != a.date or not meta.get("live"):
        print("::error title=出走表サイト紹介ショートを投稿できません::本物のデータで作った、この日の動画ではありません。投稿しません"); return 1
    privacy = U.read_privacy()
    title = meta["title"][:100].replace("<", "(").replace(">", ")")
    desc = U.clean_desc(meta["description"])
    miss = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if miss:
        print(f"::error title=投稿できません::GitHubのシークレットがありません: {', '.join(miss)}"); return 1
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    creds = Credentials(token=None, refresh_token=os.environ["YT_REFRESH_TOKEN"], client_id=os.environ["YT_CLIENT_ID"],
                        client_secret=os.environ["YT_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token", scopes=U.SCOPES)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        print(f"::error title=投稿できません::YouTubeの鍵(YT_REFRESH_TOKEN)が使えません({e})"); return 1
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    send_privacy, publish_at, plan_txt = U.plan_status(privacy)
    status = {"privacyStatus": send_privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    if publish_at: status["publishAt"] = publish_at
    body = {"snippet": {"title": title, "description": desc, "tags": meta["tags"], "categoryId": "17",
                        "defaultLanguage": "ja", "defaultAudioLanguage": "ja"}, "status": status}
    label = f"予約公開 {plan_txt}" if publish_at else f"すぐ{send_privacy}"
    print(f"[news short upload] {os.path.basename(mp4)} 公開設定={privacy} → {label}\n[news short upload] タイトル: {title}", flush=True)
    try:
        resp = U.do_upload(youtube, mp4, body)
    except HttpError as e:
        print(f"::error title=投稿に失敗しました::{e.resp.status} {e.content.decode('utf-8', errors='ignore')[:600]}"); return 1
    vid = resp["id"]
    print(f"[news short done] 投稿できました: https://youtu.be/{vid} (指定 {label})")
    os.makedirs(os.path.dirname(rec), exist_ok=True)
    json.dump({"videoId": vid, "privacy": privacy, "publishAt": publish_at, "title": title, "key": meta["key"],
               "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"}, open(rec, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(f"### 出走表サイト紹介ショートをYouTubeに投稿しました({a.date})\n公開設定: {privacy}({label})\n\n- 動画: https://youtu.be/{vid}\n- 管理画面: https://studio.youtube.com/video/{vid}/edit\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
