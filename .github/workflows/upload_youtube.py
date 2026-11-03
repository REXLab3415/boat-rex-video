#!/usr/bin/env python3
"""out/ の動画(mp4)と概要欄(description.txt)を、YouTubeに投稿する。

必要な環境変数: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN
任意: YT_PRIVACY (private=非公開 / unlisted=限定公開 / public=公開。既定は private)
"""
import glob
import json
import os
import sys
import time

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
OUT = os.environ.get("OUT_DIR", "out")
LEAK = "(YouTubeの「改変または合成されたコンテンツ」にチェック)"  # 投稿者向けのメモ。公開の概要欄には出さない


def fail(msg):
    print(f"::error::{msg}")
    sys.exit(1)


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        fail(f"{name} が空です。GitHubの Settings → Secrets and variables → Actions に登録されているか確認してください")
    return v


def get_access_token():
    r = requests.post(TOKEN_URL, data={
        "client_id": env("YT_CLIENT_ID"),
        "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }, timeout=60)
    if r.status_code != 200:
        try:
            j = r.json()
            detail = f"{j.get('error')} / {j.get('error_description')}"
        except Exception:
            detail = r.text[:300]
        hint = ""
        if "invalid_grant" in detail:
            hint = "(YT_REFRESH_TOKEN が無効か、期限切れです。Google側で取り直しが必要です)"
        fail(f"Googleの認証に失敗しました: {detail} {hint}")
    return r.json()["access_token"]


def clean(text):
    # タイトル・概要欄に < > は使えない
    return text.replace("<", "＜").replace(">", "＞")


def already_uploaded(token, title):
    """同じタイトルの動画が、すでにあるか。True/False。調べられないときは None"""
    h = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(f"{API}/channels", headers=h, timeout=60,
                         params={"part": "contentDetails", "mine": "true"})
        if r.status_code != 200:
            return None
        items = r.json().get("items") or []
        if not items:
            return None
        pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        r = requests.get(f"{API}/playlistItems", headers=h, timeout=60,
                         params={"part": "snippet", "playlistId": pl, "maxResults": 50})
        if r.status_code != 200:
            return None
        return any(it["snippet"]["title"] == title for it in r.json().get("items", []))
    except Exception:
        return None


def start_session(token, meta, size):
    h = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4",
    }
    params = {"uploadType": "resumable", "part": "snippet,status"}
    body = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    r = requests.post(UPLOAD_URL, params=params, headers=h, data=body, timeout=60)
    if r.status_code == 400 and "containsSyntheticMedia" in r.text:
        print("::warning::「合成コンテンツ」の自動チェックが受け付けられませんでした。チェックなしで投稿します。YouTubeの画面で手動でチェックしてください")
        meta["status"].pop("containsSyntheticMedia", None)
        body = json.dumps(meta, ensure_ascii=False).encode("utf-8")
        r = requests.post(UPLOAD_URL, params=params, headers=h, data=body, timeout=60)
    if r.status_code != 200 or "Location" not in r.headers:
        fail(f"投稿の開始に失敗しました(HTTP {r.status_code}): {r.text[:500]}")
    return r.headers["Location"]


def main():
    privacy = os.environ.get("YT_PRIVACY", "private").strip() or "private"
    if privacy not in ("private", "unlisted", "public"):
        fail(f"YT_PRIVACY が正しくありません: {privacy}")

    mp4s = sorted(glob.glob(os.path.join(OUT, "boat_check_*.mp4")))
    if not mp4s:
        fail(f"{OUT}/ に動画(boat_check_*.mp4)がありません")
    mp4 = mp4s[-1]
    with open(os.path.join(OUT, "description.txt"), encoding="utf-8") as f:
        desc = f.read().replace(LEAK, "").strip() + "\n"
    title = clean(desc.splitlines()[0].strip())[:100]
    desc = clean(desc)
    size = os.path.getsize(mp4)
    print(f"動画: {mp4} ({size / 1e6:.1f} MB) / タイトル: {title} / 公開設定: {privacy}")

    token = get_access_token()

    dup = already_uploaded(token, title)
    if dup:
        print("同じタイトルの動画が、すでに投稿されています。二重投稿を防ぐため、投稿しません。")
        return 0
    if dup is None:
        print("::warning::投稿ずみかどうかを調べられませんでした(権限が足りない可能性)。二重投稿の防止が効いていません")

    meta = {
        "snippet": {
            "title": title,
            "description": desc,
            "categoryId": "17",
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }

    last = ""
    for attempt in range(1, 4):
        try:
            loc = start_session(token, meta, size)
            with open(mp4, "rb") as fh:
                r = requests.put(loc, data=fh, timeout=(30, 1800), allow_redirects=False,
                                 headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
            if r.status_code in (200, 201):
                j = r.json()
                vid = j["id"]
                got = (j.get("status") or {}).get("privacyStatus", "?")
                url = f"https://www.youtube.com/watch?v={vid}"
                print(f"投稿できました: {url} (公開設定: {got})")
                if got != privacy:
                    print(f"::warning::希望は {privacy} でしたが、実際は {got} です(Google側の審査が済んでいないと、非公開に固定されます)")
                summary = os.environ.get("GITHUB_STEP_SUMMARY")
                if summary:
                    with open(summary, "a", encoding="utf-8") as sf:
                        sf.write(f"### YouTubeに投稿しました\n{url}\n\n公開設定: {got}\n")
                return 0
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except requests.RequestException as e:
            last = f"通信エラー: {e}"
        print(f"::warning::投稿に失敗({attempt}/3回目): {last}")
        if attempt < 3:
            time.sleep(30)
            if already_uploaded(token, title):
                print("失敗の表示でしたが、動画は上がっていました。ここで終わります。")
                return 0
    fail(f"3回やっても投稿できませんでした: {last}")


if __name__ == "__main__":
    sys.exit(main())
