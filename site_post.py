#!/usr/bin/env python3
"""出走表サイト(https://boat-rex-pro.com/)の今日のトップ画面を撮って、固定の説明文といっしょに送る。
  Instagram … トップ画面(上から4:5の範囲)の画像を、自動で投稿する
  X         … 固定の投稿文+「Xの投稿画面を開くリンク」を、メールで送る(投稿はREXが手でタップ)。
              メールには、YouTubeショートが選んだレースの出走表ページの画像を付ける
  python site_post.py --date 20261119 --out out                 → 今日の分を送る(同じ日は、Instagram・メールとも1回だけ)
  python site_post.py --date 20261119 --out out --force         → 送信済みでも、もう一度送る
  python site_post.py --date 20261118 --base https://boat-rex-pro.com/2026-11-18/ --out out --check
                                                                → 撮影と文の確認だけ(投稿もメールもしない)
今日の日付がトップ画面に出ていなければ(サイトの更新前)、何も送らずに赤で止まる(あとの時刻の回でやり直す)。
"""
import argparse, json, os, random, smtplib, sys, time, urllib.parse
from datetime import datetime, timezone, timedelta
from email.header import Header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urljoin

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import x_post_mail as X          # noqa: E402  (文字数の数え方)
import instagram_reel as I       # noqa: E402  (Instagramへの投稿の部品)
import news_capture as NC        # noqa: E402  (サイト紹介ショートと同じ「場」の選び方)

SITE = "https://boat-rex-pro.com/"
IG_W, IG_H = 1080, 1350                      # Instagramの画像は、縦長が4:5まで(トップ画面は縦に長すぎるので、上から切り出す)
CROP_H = 1500                                # トップ画面(幅1200)の、上から1500pxが 4:5

X_TEXT = ("BOAT REX PRO オリジナル出走表(無料・毎朝更新)\n"
          "全場の出走表を、過去1年の独自データで。モーター気配・節間成績・ST・コース別1着率・決まり手・3連単の出目まで見られます。\n"
          "#ボートレース #競艇\n" + SITE)
IG_TEXT = ("BOAT REX PRO オリジナル出走表(無料・毎朝更新)\n"
           "開催している全場を、場ごとの新聞にしました。公式の成績データから、過去1年の実績を独自に計算しています。\n\n"
           "・勝率ランク(SSS/SS/S)と平均STランク\n"
           "・モーター気配(5段階の矢印)と、節間成績・節間平均ST\n"
           "・艇番別の全国/当地の勝率・2連率・3連率\n"
           "・1号艇の逃げ率・差され率・まくられ率\n"
           "・場の特徴、コース別1着率、決まり手ランキング\n"
           "・前日の展示タイムTOP10、3連単の出目ランキング\n"
           "・解析ツールの買い目(朝に公開。後出しではありません)\n\n"
           + SITE + "\n"
           "的中・収益を保証するものではありません。\n"
           "#ボートレース #競艇 #出走表")


def capture(base, out_dir, date, check_images=True, log=print):
    """トップ画面(Instagram用)と、選ばれたレースの出走表ページ(Xのメール用)を撮る。失敗したら例外"""
    from playwright.sync_api import sync_playwright
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    base = base.rstrip("/") + "/"
    mm, dd = int(date[4:6]), int(date[6:8])
    res = {}
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--font-render-hinting=none"])

        def newpage(w):
            ctx = br.new_context(viewport={"width": w, "height": 1000}, device_scale_factor=1, locale="ja-JP", timezone_id="Asia/Tokyo")
            pg = ctx.new_page()
            pg.route("**/api/hit*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"ok":true}'))   # 訪問者カウンターを増やさない
            pg.route("**/*cloudflareinsights.com/**", lambda r: r.abort())
            return pg

        # ---- トップ画面 ----
        pg = newpage(1200)
        pg.goto(base, wait_until="load", timeout=60000)
        pg.wait_for_function("document.fonts.ready.then(()=>true)")
        top_txt = pg.inner_text("body")
        if f"{mm}月{dd}日" not in top_txt:
            raise RuntimeError(f"今日({mm}月{dd}日)の出走表ではありません(トップ画面に日付がありません)。サイトの更新前かもしれません")
        if check_images:
            ok = False
            for _ in range(20):          # 画像の読み込みを、最長20秒待つ
                bad = pg.evaluate("[...document.images].filter(i=>!(i.complete&&i.naturalWidth>0)).map(i=>i.src)")
                if not bad:
                    ok = True
                    break
                pg.wait_for_timeout(1000)
            if not ok:
                raise RuntimeError("トップ画面の画像が表示されません: " + " / ".join(bad[:3]))
        pg.wait_for_timeout(800)
        cards = pg.evaluate("""[...document.querySelectorAll('a.vc')].map(a=>({href:a.getAttribute('href'),
            grade:((a.querySelector('.bg')||{}).textContent||'').trim(), name:a.querySelector('.nm').textContent.trim()}))""")
        if not cards:
            raise RuntimeError("トップ画面に、開催中の場がありません(a.vc が0個)")
        card = NC.pick_card(cards, int(date))        # YouTubeのサイト紹介ショートと同じ選び方(グレードが一番高い場。同じなら日付で決める)
        H = int(pg.evaluate("document.documentElement.scrollHeight"))
        raw = os.path.join(out_dir, "_top_full.png")
        pg.screenshot(path=raw, clip={"x": 0, "y": 0, "width": 1200, "height": min(H, CROP_H)}, full_page=True)
        im = Image.open(raw).convert("RGB")
        if im.height < CROP_H:                       # 短い日は、下を白で足して4:5にする
            canvas = Image.new("RGB", (1200, CROP_H), (255, 255, 255)); canvas.paste(im, (0, 0)); im = canvas
        top = os.path.join(out_dir, f"site_top_{date}.jpg")
        im.resize((IG_W, IG_H), Image.LANCZOS).save(top, "JPEG", quality=92)
        res["top"] = top
        log(f"[トップ] {len(cards)}場開催 / 画像 {IG_W}x{IG_H} / 選んだ場: {card['name']}({card['grade'] or 'グレードなし'})")
        pg.context.close()

        # ---- 選ばれた場の、最終レースの出走表ページ ----
        pg = newpage(1782)
        pg.goto(urljoin(base, card["href"]), wait_until="load", timeout=60000)
        pg.wait_for_function("document.fonts.ready.then(()=>true)"); pg.wait_for_timeout(1200)
        ids = pg.evaluate("[...document.querySelectorAll('.rc')].map(e=>parseInt(e.id.replace('rc','')))")
        if not ids:
            raise RuntimeError("レースがありません(.rc が0個)")
        n = max(ids)                                  # サイト紹介ショートと同じ「最終レース」
        pg.evaluate("(n)=>{location.hash='#r'+n}", n); pg.wait_for_timeout(700)
        if pg.evaluate("(n)=>getComputedStyle(document.querySelector('#rc'+n)).display", n) == "none":
            raise RuntimeError(f"{n}Rの出走表が表示されません")
        title = pg.inner_text(f"#rc{n} .rt").replace("← スワイプ", "").strip()
        rp = os.path.join(out_dir, f"_race_{date}.png")
        H2 = int(pg.evaluate("document.documentElement.scrollHeight")) + 40      # ページ全体が画面に入る高さにして、出走表の箱の座標で切り出す
        pg.set_viewport_size({"width": 1782, "height": min(H2, 6000)}); pg.wait_for_timeout(500)
        pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(200)
        box = pg.evaluate("""(n)=>{const b=document.querySelector('#rc'+n).getBoundingClientRect(); return {x:b.x+scrollX,y:b.y+scrollY,width:b.width,height:b.height}}""", n)
        if box["width"] < 600 or box["height"] < 200:
            raise RuntimeError(f"{n}Rの出走表の大きさが想定と違います({box['width']:.0f}x{box['height']:.0f})")
        pg.screenshot(path=rp, clip=box)
        race = os.path.join(out_dir, f"race_{date}.jpg")
        Image.open(rp).convert("RGB").save(race, "JPEG", quality=90)
        res["race"] = race
        res["info"] = {"venue": card["name"], "no": n, "grade": card["grade"], "title": title}
        log(f"[出走表] {card['name']} {n}R({title}) / {os.path.getsize(race) / 1e6:.1f}MB")
        br.close()
    return res


def publish_site_image(token, uid, url, caption):
    """画像の投稿(サイトの画面なので、「AIで作った」の申告は付けない)"""
    res = I.api("POST", f"{uid}/media", {"image_url": url, "caption": caption}, token)
    cid = res["id"]
    print(f"[ig] 投稿の準備を始めました(番号 {cid})")
    for _ in range(30):
        st = I.api("GET", cid, {"fields": "status_code,status"}, token)
        code = st.get("status_code", "")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise I.ApiError(f"Instagramが画像を受け付けませんでした: {st}")
        time.sleep(10)
    else:
        raise I.ApiError("5分待っても処理が終わりませんでした")
    pub = I.api("POST", f"{uid}/media_publish", {"creation_id": cid}, token)
    mid = pub["id"]
    link = ""
    try:
        link = I.api("GET", mid, {"fields": "permalink"}, token).get("permalink", "")
    except I.ApiError:
        pass
    return mid, link


def send_mail(date, text, race_jpg, info):
    user = os.environ.get("MAIL_USER", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not pw:
        raise RuntimeError("GMAIL_APP_PASSWORD(または MAIL_USER)が登録されていないため、メールを送れません")
    m, d = int(date[4:6]), int(date[6:8])
    wt = X.x_weight(text.replace(SITE, "")) + 23
    intent = "https://x.com/intent/tweet?text=" + urllib.parse.quote(text, safe="")
    subject = f"【X投稿】{m}/{d} 出走表サイトの紹介(画像つき)"
    cap = f"{info['venue']}{info['no']}R" + (f"({info['grade']})" if info.get("grade") else "")
    plain = ("下のリンクを押すと、文章が入った状態でXの投稿画面が開きます。\n"
             f"画像は、このメールに付いている「{cap}の出走表」です。保存して、Xの投稿画面で画像を追加してください。\n"
             "開かないとき・文字が崩れるときは、下の「投稿文」をコピーして、Xに貼り付けてください。\n"
             f"\n▼Xの投稿画面を開く\n{intent}\n\n▼投稿文(コピー用)\n{text}\n")
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = ("<p>下のリンクを押すと、文章が入った状態でXの投稿画面が開きます。<br>"
            f"画像は、このメールに付いている「{cap}の出走表」です。保存して、Xの投稿画面で画像を追加してください。<br>"
            "開かないとき・文字が崩れるときは、下の「投稿文」をコピーして、Xに貼り付けてください。</p>"
            f"<p><a href=\"{intent}\" style=\"font-size:20px;font-weight:bold\">▶ Xの投稿画面を開く</a></p>"
            f"<p>▼投稿文(コピー用)</p><p style=\"white-space:pre-wrap;border:1px solid #ccc;padding:10px\">{esc(text)}</p>")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(subject, "utf-8"); msg["From"] = user; msg["To"] = to
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain, "plain", "utf-8")); alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)
    with open(race_jpg, "rb") as f:
        img = MIMEImage(f.read(), _subtype="jpeg")
    img.add_header("Content-Disposition", "attachment", filename=("utf-8", "", f"{cap}_出走表_{date}.jpg"))
    msg.attach(img)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("Gmailにログインできませんでした。GMAIL_APP_PASSWORD(16桁のアプリパスワード)が正しいか、2段階認証がオンか確認してください")
    return to, subject, wt


def record(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(data, at=jst), f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--base", default=SITE)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check", action="store_true", help="撮影と文の確認だけ(投稿もメールもしない)")
    ap.add_argument("--skip-image-check", action="store_true", help="試験用: 画像の読み込み確認を飛ばす")
    a = ap.parse_args()
    date = a.date or datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    rec_ig = os.path.join(HERE, "uploaded", f"{date}_site_ig.json")
    rec_mail = os.path.join(HERE, "uploaded", f"{date}_site_mail.json")
    need_ig = a.force or not os.path.exists(rec_ig)
    need_mail = a.force or not os.path.exists(rec_mail)
    if not a.check and not need_ig and not need_mail:
        print(f"::notice::{date} は、Instagramもメールも送信済みです。何もしません(もう一度送るときは force にチェックを入れてください)")
        return 0
    print(f"[文字数] X {X.x_weight(X_TEXT.replace(SITE, '')) + 23} / 280 ・ Instagram {len(IG_TEXT)} / 2200")
    try:
        r = capture(a.base, a.out, date, check_images=not a.skip_image_check)
    except Exception as e:
        print(f"::error title=サイトの画面を撮れませんでした::{e}")
        return 1
    if a.check:
        print("[確認のみ] 投稿もメールもしません。画像は out に保存しました")
        return 0
    rc = 0
    # ---- Instagram ----
    if need_ig:
        try:
            token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
            if not token:
                raise I.ApiError("GitHubのシークレット IG_ACCESS_TOKEN がありません")
            uid, name = I.find_account(token)
            url = I.host_file(r["top"], "site-tmp", f"site_{date}.jpg", date)
            mid, link = publish_site_image(token, uid, url, IG_TEXT)
            record(rec_ig, {"mediaId": mid, "permalink": link})
            print(f"[ig] 投稿しました: {link or mid}")
        except Exception as e:
            print(f"::error title=Instagramに投稿できませんでした::{e}")
            rc = 1
    # ---- Xのメール ----
    if need_mail:
        try:
            to, subject, wt = send_mail(date, X_TEXT, r["race"], r["info"])
            record(rec_mail, {"to": to, "subject": subject, "race": r["info"]})
            print(f"[mail] 送りました: {to}  件名={subject}")
        except Exception as e:
            print(f"::error title=メールを送れませんでした::{e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
