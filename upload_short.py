#!/usr/bin/env python3
"""out/ にできたショート動画(short_日付.mp4)を、YouTubeに投稿する。
  - 公開の設定は youtube_privacy.txt の1語(横動画と同じファイルを読む。夜に動いたときの朝6:00予約公開も、横動画と同じ決まり)。
  - 同じ日をすでに投稿していたら(uploaded/日付_short.json がある)、飛ばす。--force で上げ直す。
  - 鍵は環境変数 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN(横動画と同じ)。
  - 投稿の部品は、upload_youtube.py のものをそのまま使う(横動画の動きは変えない)。
"""
import argparse, glob, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import upload_youtube as U  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="例 20261102。空欄なら out の中のショートの日付")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--force", action="store_true", help="投稿済みの日でも、もう一度上げる")
    args = ap.parse_args()

    mp4s = sorted(glob.glob(os.path.join(args.out, "short_*.mp4")))
    if args.date:
        mp4s = [p for p in mp4s if p.endswith(f"short_{args.date}.mp4")]
    if not mp4s:
        print("::notice::投稿するショート(out/short_日付.mp4)がありません。ショートは投稿しません(作る手順の赤い文を確認してください)")
        return 0
    mp4 = mp4s[-1]
    date = re.search(r"short_(\d{8})\.mp4$", mp4).group(1)

    rec = os.path.join(HERE, "uploaded", f"{date}_short.json")
    if os.path.exists(rec) and not args.force:
        print(f"::notice::{date} のショートはすでに投稿済みです(uploaded/{date}_short.json)。もう一度上げるときは、手動実行で「force」にチェックを入れてください")
        return 0

    privacy = U.read_privacy()
    meta_path = os.path.join(args.out, "short_meta.json")
    if not os.path.exists(meta_path):
        print("::error title=ショートを投稿できません::out/short_meta.json がありません。投稿しません")
        return 1
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    if meta.get("date") != date:
        print(f"::error title=ショートを投稿できません::short_meta.json の日付({meta.get('date')})が、動画の日付({date})と違います。投稿しません")
        return 1
    title = meta["title"][:100].replace("<", "(").replace(">", ")")
    tags, desc = meta["tags"], U.clean_desc(meta["description"])

    miss = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if miss:
        print(f"::error title=ショートを投稿できません::GitHubのシークレットがありません: {', '.join(miss)}")
        return 1

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = Credentials(token=None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        token_uri="https://oauth2.googleapis.com/token", scopes=U.SCOPES)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        print(f"::error title=ショートを投稿できません::YouTubeの鍵(YT_REFRESH_TOKEN)が使えません。失効した可能性があります({e})")
        return 1
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    send_privacy, publish_at, plan_txt = U.plan_status(privacy)
    status = {"privacyStatus": send_privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {"title": title, "description": desc, "tags": tags, "categoryId": "17",
                    "defaultLanguage": "ja", "defaultAudioLanguage": "ja"},
        "status": status,
    }
    plan_label = f"予約公開 {plan_txt}" if publish_at else f"すぐ{send_privacy}"
    print(f"[short upload] {os.path.basename(mp4)} ({os.path.getsize(mp4) / 1e6:.1f} MB) 公開設定={privacy} → {plan_label}\n[short upload] タイトル: {title}", flush=True)
    try:
        resp = U.do_upload(youtube, mp4, body)
    except HttpError as e:
        print(f"::error title=ショートの投稿に失敗しました::{e.resp.status} {e.content.decode('utf-8', errors='ignore')[:600]}")
        return 1

    vid = resp["id"]
    got = resp.get("status", {}).get("privacyStatus", "?")
    got_at = resp.get("status", {}).get("publishAt")
    print(f"[short done] 投稿できました: https://youtu.be/{vid} (指定 {plan_label} / 返ってきた設定 {got} {got_at or ''})")
    if publish_at and not got_at:
        print("::warning::予約公開を指定しましたが、YouTubeから返ってきた情報に公開予定の日時がありません。YouTube Studioで、このショートに公開予定の日時が付いているか確認してください")
    os.makedirs(os.path.dirname(rec), exist_ok=True)
    with open(rec, "w", encoding="utf-8") as f:
        json.dump({"videoId": vid, "privacy": privacy, "publishAt": publish_at, "title": title,
                   "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"}, f, ensure_ascii=False, indent=1)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(f"### ショートをYouTubeに投稿しました({date})\n指定した公開設定: {privacy}({plan_label})\n\n"
                    f"- 動画: https://youtu.be/{vid}\n- 管理画面(公開設定を確認): https://studio.youtube.com/video/{vid}/edit\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
