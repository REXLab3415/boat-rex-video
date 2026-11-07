#!/usr/bin/env python3
"""その日のショート動画(out/short_日付.mp4)を、Xと同じ投稿文で、Instagramのリールに投稿する。
続けて、その日のサムネイル画像(out/thumbnail_日付.jpg)を、同じ投稿文で、Instagramの普通の投稿(画像)にも投稿する。
  python instagram_reel.py --date 20261105 --out out     → 投稿する(同じ日は1回だけ。記録 uploaded/日付_ig.json と 日付_ig_thumb.json)
  python instagram_reel.py --date 20261105 --force       → 投稿済みでも、もう一度投稿する
  python instagram_reel.py --date 20261105 --dry-run     → 投稿せず、投稿文だけ画面に出す
  python instagram_reel.py --check                       → 接続の確認だけ(投稿はしない)
鍵は環境変数 IG_ACCESS_TOKEN(必須)。IG_USER_ID は任意(なければ、鍵からアカウントを探す)。
動画・画像は、Instagramが「ネット上のURL」から取りに来るため、公開側リポジトリの専用の枝(動画=reel-tmp、画像=thumb-tmp)に、1つだけ上書きして置く。
ツールの的中が0件の日(ショートが作られない日)は、何もしない。
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import x_post_mail as X  # noqa: E402  (Xの投稿文を作る部分をそのまま使う)

GRAPH = "https://graph.facebook.com"
VER = os.environ.get("IG_API_VERSION", "v26.0")


class ApiError(Exception):
    pass


def api(method, path, params=None, token=""):
    url = f"{GRAPH}/{VER}/{path.lstrip('/')}"
    params = params or {}
    data = None
    if method == "GET":
        if params:
            url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise ApiError(f"{e.code} {body[:700]}")
    except Exception as e:
        raise ApiError(f"{type(e).__name__}: {e}")


def find_account(token):
    """投稿するInstagramアカウントの番号(と名前)。IG_USER_ID があればそれを使う"""
    uid = os.environ.get("IG_USER_ID", "").strip()
    if uid:
        return uid, ""
    want = os.environ.get("IG_USERNAME", "boatrex3415").strip()
    res = api("GET", "me/assigned_instagram_accounts", {"fields": "id,username"}, token)
    accts = res.get("data", [])
    if not accts:
        raise ApiError("鍵に結びついたInstagramアカウントが見つかりません(me/assigned_instagram_accounts が空)")
    for a in accts:
        if a.get("username") == want:
            return a["id"], a.get("username", "")
    if len(accts) == 1:
        return accts[0]["id"], accts[0].get("username", "")
    raise ApiError("アカウントが複数あり、どれか決められません: " + ", ".join(a.get("username", "?") for a in accts))


def host_file(path, branch, name, date, limit_mb=95):
    """ファイルを、公開リポジトリの専用の枝(1つだけ・毎回上書き)に置いて、取りに来てもらうURLを返す"""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not repo or not tok:
        raise ApiError("GITHUB_REPOSITORY / GITHUB_TOKEN がありません(GitHubの実行の中でだけ動きます)")
    size = os.path.getsize(path)
    if size > limit_mb * 1024 * 1024:
        raise ApiError(f"ファイルが大きすぎます({size / 1e6:.0f}MB)。置けないため投稿しません")
    tmp = tempfile.mkdtemp()
    shutil.copy(path, os.path.join(tmp, name))

    def git(*a):
        p = subprocess.run(["git", *a], cwd=tmp, capture_output=True, text=True)
        if p.returncode != 0:
            err = (p.stderr or p.stdout).replace(tok, "***")
            raise ApiError(f"git {a[0]} に失敗: {err[:400]}")
        return p.stdout.strip()

    git("init", "-q", "-b", branch)
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", name)
    git("commit", "-q", "-m", f"{branch} {date}")
    git("push", "-f", f"https://x-access-token:{tok}@github.com/{repo}.git", branch)
    sha = git("rev-parse", "HEAD")
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{name}"
    for i in range(8):   # 置いた直後は見えないことがあるので、少し待つ
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status in (200, 206):
                    print(f"[host] URLを確認できました: {url} (Content-Type: {r.headers.get('Content-Type')})")
                    return url
        except Exception as e:
            print(f"[host] URLをまだ開けません({i + 1}/8): {type(e).__name__}")
        time.sleep(5)
    raise ApiError("置いたファイルのURLを開けませんでした: " + url)


def publish_image(token, uid, url, caption):
    params = {"image_url": url, "caption": caption, "is_ai_generated": "true"}
    try:
        res = api("POST", f"{uid}/media", params, token)
    except ApiError as e:
        if "is_ai_generated" in str(e):
            print("::warning::「AIで作った」の申告(is_ai_generated)が受け付けられなかったため、付けずに投稿します")
            params.pop("is_ai_generated")
            res = api("POST", f"{uid}/media", params, token)
        else:
            raise
    cid = res["id"]
    print(f"[ig image] 投稿の準備を始めました(番号 {cid})")
    for i in range(30):   # 最長5分
        st = api("GET", cid, {"fields": "status_code,status"}, token)
        code = st.get("status_code", "")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise ApiError(f"Instagramが画像を受け付けませんでした: {st}")
        time.sleep(10)
    else:
        raise ApiError("5分待っても処理が終わりませんでした")
    pub = api("POST", f"{uid}/media_publish", {"creation_id": cid}, token)
    mid = pub["id"]
    link = ""
    try:
        link = api("GET", mid, {"fields": "permalink"}, token).get("permalink", "")
    except ApiError:
        pass
    return mid, link


def publish_reel(token, uid, url, caption):
    params = {"media_type": "REELS", "video_url": url, "caption": caption,
              "share_to_feed": "true", "is_ai_generated": "true"}
    try:
        res = api("POST", f"{uid}/media", params, token)
    except ApiError as e:
        if "is_ai_generated" in str(e):
            print("::warning::「AIで作った」の申告(is_ai_generated)が受け付けられなかったため、付けずに投稿します")
            params.pop("is_ai_generated")
            res = api("POST", f"{uid}/media", params, token)
        else:
            raise
    cid = res["id"]
    print(f"[ig] 投稿の準備を始めました(番号 {cid})。Instagramが動画を処理するのを待ちます")
    last = ""
    for i in range(90):   # 最長15分
        time.sleep(10)
        st = api("GET", cid, {"fields": "status_code,status"}, token)
        code = st.get("status_code", "")
        if code != last:
            print(f"[ig] 状態: {code} {st.get('status', '')}")
            last = code
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise ApiError(f"Instagramが動画を受け付けませんでした: {st}")
    else:
        raise ApiError("15分待っても処理が終わりませんでした")
    pub = api("POST", f"{uid}/media_publish", {"creation_id": cid}, token)
    mid = pub["id"]
    link = ""
    try:
        link = api("GET", mid, {"fields": "permalink"}, token).get("permalink", "")
    except ApiError:
        pass
    return mid, link


def save_record(rec, mid, link):
    os.makedirs(os.path.dirname(rec), exist_ok=True)
    with open(rec, "w", encoding="utf-8") as f:
        json.dump({"mediaId": mid, "permalink": link,
                   "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"}, f, ensure_ascii=False, indent=1)


def summary(text):
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="接続の確認だけ(投稿しない)")
    a = ap.parse_args()

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()

    if a.check:
        if not token:
            print("::error::GitHubのシークレット IG_ACCESS_TOKEN がありません")
            return 1
        try:
            uid, name = find_account(token)
            info = api("GET", uid, {"fields": "username"}, token)
        except ApiError as e:
            print(f"::error title=Instagramに接続できません::{e}")
            return 1
        print(f"[check] 接続できました: アカウント番号 {uid} / {info}")
        return 0

    mp4s = sorted(glob.glob(os.path.join(a.out, "short_*.mp4")))
    thumbs = sorted(glob.glob(os.path.join(a.out, "thumbnail_*.jpg")))
    if a.date:
        mp4s = [p for p in mp4s if p.endswith(f"short_{a.date}.mp4")]
        thumbs = [p for p in thumbs if p.endswith(f"thumbnail_{a.date}.jpg")]
    dates = sorted({re.search(r"_(\d{8})\.(?:mp4|jpg)$", p).group(1) for p in mp4s + thumbs})
    if not dates:
        print("::notice::投稿するショート・サムネイルがありません。Instagramには投稿しません(的中0件の日は作られません)")
        return 0
    date = a.date or dates[-1]
    mp4 = next((p for p in mp4s if p.endswith(f"short_{date}.mp4")), "")
    thumb = next((p for p in thumbs if p.endswith(f"thumbnail_{date}.jpg")), "")

    with open(os.path.join(HERE, "days", f"{date}.json"), encoding="utf-8") as f:
        day = json.load(f)
    post = X.build_post(date, day)
    if post is None:
        print(f"::notice::{date} はツールの的中が0件のため、Instagramには投稿しません")
        return 0
    url = X.video_url(date)
    caption = post["text"] + f"\n{X.HASHTAGS}" + (f"\n{url}" if url else "")
    print("---- 投稿文(Xと同じ) ----")
    print(caption)
    if a.dry_run:
        print(f"[dry-run] リール用の動画: {mp4 or 'なし'} / 画像用のサムネイル: {thumb or 'なし'}")
        return 0
    if not token:
        print("::error title=Instagramに投稿できません::GitHubのシークレット IG_ACCESS_TOKEN がありません")
        return 1

    rc = 0
    try:
        uid, name = find_account(token)
    except ApiError as e:
        print(f"::error title=Instagramに接続できません::{e}")
        return 1
    print(f"[ig] 投稿先のアカウント番号: {uid} {name}")

    # ---- リール(ショート動画) ----
    rec = os.path.join(HERE, "uploaded", f"{date}_ig.json")
    if not mp4:
        print("::notice::ショート(out/short_日付.mp4)がないため、リールは投稿しません")
    elif os.path.exists(rec) and not a.force:
        print(f"::notice::{date} のリールはすでに投稿済みです(uploaded/{date}_ig.json)。もう一度上げるときは force にチェックを入れてください")
    else:
        try:
            vurl = host_file(mp4, "reel-tmp", "reel.mp4", date)
            mid, link = publish_reel(token, uid, vurl, caption)
            print(f"[ig done] リールを投稿できました: {link or mid}")
            save_record(rec, mid, link)
            summary(f"### Instagramのリールに投稿しました({date})\n\n- {link or mid}\n")
        except ApiError as e:
            print(f"::error title=Instagramへのリール投稿に失敗しました::{e}")
            rc = 1

    # ---- 画像(サムネイル)。リールが失敗しても、続けて試す ----
    rec2 = os.path.join(HERE, "uploaded", f"{date}_ig_thumb.json")
    if not thumb:
        print("::notice::サムネイル(out/thumbnail_日付.jpg)がないため、画像は投稿しません")
    elif os.path.exists(rec2) and not a.force:
        print(f"::notice::{date} の画像はすでに投稿済みです(uploaded/{date}_ig_thumb.json)。もう一度上げるときは force にチェックを入れてください")
    else:
        try:
            iurl = host_file(thumb, "thumb-tmp", "thumb.jpg", date, limit_mb=7)
            mid, link = publish_image(token, uid, iurl, caption)
            print(f"[ig done] 画像を投稿できました: {link or mid}")
            save_record(rec2, mid, link)
            summary(f"### Instagramに画像(サムネイル)を投稿しました({date})\n\n- {link or mid}\n")
        except ApiError as e:
            print(f"::error title=Instagramへの画像投稿に失敗しました::{e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
