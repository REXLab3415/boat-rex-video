#!/usr/bin/env python3
"""out/ にできた動画を、YouTubeに投稿する。
  - 公開の設定は youtube_privacy.txt の1語(public / unlisted / private)。
  - 同じ日をすでに投稿していたら(uploaded/日付.json がある)、飛ばす。--force で上げ直す。
  - 鍵は環境変数 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN(GitHubのシークレット)。
"""
import argparse, glob, json, os, random, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
PRIVACY_OK = ("public", "unlisted", "private")
TAGS = ["ボートレース", "競艇", "答え合わせ", "3連単", "払戻金", "BOAT REX PRO"]


def read_privacy():
    p = os.path.join(HERE, "youtube_privacy.txt")
    if not os.path.exists(p):
        print("::error::youtube_privacy.txt がありません(中身は public / unlisted / private のどれか1語)")
        sys.exit(1)
    for ln in open(p, encoding="utf-8"):
        v = ln.strip().lower()
        if v and not v.startswith("#"):
            if v not in PRIVACY_OK:
                print(f"::error::youtube_privacy.txt の中身が正しくありません({v})。public / unlisted / private のどれか1語にしてください")
                sys.exit(1)
            return v
    print("::error::youtube_privacy.txt が空です")
    sys.exit(1)


def make_title(date, day):
    m, d = int(date[4:6]), int(date[6:])
    t = f"【ボートレース答え合わせ】{m}月{d}日 {len(day['venues'])}場{len(day['races'])}レースの3連単結果と払戻金|BOAT REX PRO"
    return t[:100]


def clean_desc(text, limit=4800):
    text = text.replace("<", "(").replace(">", ")")
    b = text.encode("utf-8")
    if len(b) <= limit:
        return text
    print("::warning::概要欄が長いため、後ろを切りました")
    return b[:limit].decode("utf-8", errors="ignore")


def do_upload(youtube, path, body):
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    media = MediaFileUpload(path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, retry, last = None, 0, -1
    while resp is None:
        try:
            status, resp = req.next_chunk(num_retries=5)
            if status:
                pct = int(status.progress() * 100)
                if pct // 10 != last // 10:
                    print(f"[upload] {pct}%", flush=True)
                    last = pct
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retry < 10:
                retry += 1
                time.sleep(min(60, 2 ** retry + random.random()))
                continue
            raise
        except (ConnectionError, TimeoutError, OSError) as e:
            if retry < 10:
                retry += 1
                print(f"::warning::通信が切れたのでやり直します({e})")
                time.sleep(min(60, 2 ** retry + random.random()))
                continue
            raise
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="例 20261102。空欄なら out の中の動画の日付")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--force", action="store_true", help="投稿済みの日でも、もう一度上げる")
    args = ap.parse_args()

    mp4s = sorted(glob.glob(os.path.join(args.out, "boat_check_*.mp4")))
    if args.date:
        mp4s = [p for p in mp4s if p.endswith(f"boat_check_{args.date}.mp4")]
    if not mp4s:
        print("::notice::投稿する動画(out/boat_check_日付.mp4)がありません。投稿しません")
        return 0
    mp4 = mp4s[-1]
    date = re.search(r"boat_check_(\d{8})\.mp4$", mp4).group(1)

    rec = os.path.join(HERE, "uploaded", f"{date}.json")
    if os.path.exists(rec) and not args.force:
        print(f"::notice::{date} はすでにYouTubeに投稿済みです(uploaded/{date}.json)。もう一度上げるときは、手動実行で「force」にチェックを入れてください")
        return 0

    privacy = read_privacy()
    with open(os.path.join(HERE, "days", f"{date}.json"), encoding="utf-8") as f:
        day = json.load(f)
    with open(os.path.join(args.out, "description.txt"), encoding="utf-8") as f:
        desc = clean_desc(f.read())
    title = make_title(date, day)

    miss = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if miss:
        print(f"::error::GitHubのシークレットがありません: {', '.join(miss)}")
        return 1

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = Credentials(token=None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        print(f"::error::YouTubeの鍵(YT_REFRESH_TOKEN)が使えません。失効した可能性があります。鍵を取り直して、シークレットを入れ替えてください({e})")
        return 1
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = {
        "snippet": {"title": title, "description": desc, "tags": TAGS, "categoryId": "17",
                    "defaultLanguage": "ja", "defaultAudioLanguage": "ja"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }
    print(f"[upload] {os.path.basename(mp4)} ({os.path.getsize(mp4) / 1e6:.1f} MB) 公開設定={privacy}\n[upload] タイトル: {title}", flush=True)
    try:
        resp = do_upload(youtube, mp4, body)
    except HttpError as e:
        print(f"::error::YouTubeへの投稿に失敗しました: {e.resp.status} {e.content.decode('utf-8', errors='ignore')[:600]}")
        return 1

    vid = resp["id"]
    got = resp.get("status", {}).get("privacyStatus", "?")
    print(f"[done] 投稿できました: https://youtu.be/{vid} (指定 {privacy} / 返ってきた設定 {got})")
    os.makedirs(os.path.dirname(rec), exist_ok=True)
    with open(rec, "w", encoding="utf-8") as f:
        json.dump({"videoId": vid, "privacy": privacy, "title": title,
                   "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"}, f, ensure_ascii=False, indent=1)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(f"### YouTubeに投稿しました({date})\n指定した公開設定: {privacy}\n\n"
                    f"- 動画: https://youtu.be/{vid}\n- 管理画面(公開設定を確認): https://studio.youtube.com/video/{vid}/edit\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
