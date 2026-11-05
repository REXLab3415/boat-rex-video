#!/usr/bin/env python3
"""days/日付.json から、Xの投稿文を作って、メールで送る(無課金。GmailのSMTP+アプリパスワード)。
  python x_post_mail.py --date 20261104            → 送る(同じ日は、1回だけ。送信記録 uploaded/日付_mail.json)
  python x_post_mail.py --date 20261104 --force    → 送信済みでも、もう一度送る
  python x_post_mail.py --date 20261104 --dry-run  → 送らずに、投稿文とリンクを画面に出すだけ
ツールの買い目が的中した日だけ送る(的中0件の日は、何もしない)。
失敗しても、呼ぶ側で続ける(動画の投稿は止めない)。
"""
import argparse, glob, json, os, re, smtplib, sys, urllib.parse
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

HERE = os.path.dirname(os.path.abspath(__file__))


def latest_date():
    fs = sorted(glob.glob(os.path.join(HERE, "days", "*.json")))
    if not fs:
        return ""
    return re.search(r"(\d{8})\.json$", fs[-1]).group(1)


def video_url(date):
    """その日の横動画のURL。投稿の記録(uploaded/日付.json)から。なければ None"""
    p = os.path.join(HERE, "uploaded", f"{date}.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            vid = json.load(f).get("videoId")
    except Exception:
        return None
    return f"https://youtu.be/{vid}" if vid else None


def build_post(date, day):
    races = day["races"]
    hits = [r for r in races if r["hit"]]
    if not hits:
        return None
    top = max(hits, key=lambda r: int(r["pay"]))      # ツールが的中したレースの中の最高払戻(同額なら最初のレース)
    m, d = int(date[4:6]), int(date[6:])
    return {
        "text": (f"{m}/{d} ボートレース結果 ツールの買い目が的中(全{len(races)}レース中{len(hits)}レース的中)した中で、"
                 f"払戻金が最高だったレース {top['venue']}{top['no']}R 3連単 {top['win']} {int(top['pay']):,}円"),
        "m": m, "d": d, "nhit": len(hits), "nraces": len(races),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    date = a.date or latest_date()
    if not date:
        print("::error::days の中に日付のファイルがありません")
        return 1
    with open(os.path.join(HERE, "days", f"{date}.json"), encoding="utf-8") as f:
        day = json.load(f)
    post = build_post(date, day)
    if post is None:
        print(f"::notice::{date} はツールの的中が0件のため、投稿文を作りません(メールも送りません)")
        return 0
    rec = os.path.join(HERE, "uploaded", f"{date}_mail.json")
    if os.path.exists(rec) and not a.force and not a.dry_run:
        print(f"::notice::{date} の投稿文のメールは送信済みです(uploaded/{date}_mail.json)。もう一度送るときは force にチェックを入れてください")
        return 0

    url = video_url(date)
    text = post["text"] + (f"\n{url}" if url else "")
    intent = "https://x.com/intent/tweet?text=" + urllib.parse.quote(text, safe="")
    print("---- 投稿文 ----")
    print(text)
    print("---- 投稿画面を開くリンク ----")
    print(intent)
    if not url:
        print("::warning::横動画のURLが取れなかったため、投稿文にURLを入れていません(uploaded/日付.json がありません)")
    if a.dry_run:
        return 0

    user = os.environ.get("MAIL_USER", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not pw:
        print("::error::GMAIL_APP_PASSWORD(または MAIL_USER)が登録されていないため、メールを送れません")
        return 1

    subject = f"【X投稿】{post['m']}/{post['d']} ボートレース結果(ツール的中{post['nhit']}レース)"
    note = "" if url else "\n※横動画のURLが取れなかったため、投稿文にURLは入っていません。\n"
    plain = ("下のリンクを押すと、文章が入った状態でXの投稿画面が開きます。\n"
             "開かないとき・文字が崩れるときは、下の「投稿文」をコピーして、Xに貼り付けてください。\n"
             f"{note}\n▼Xの投稿画面を開く\n{intent}\n\n▼投稿文(コピー用)\n{text}\n")
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (f"<p>下のリンクを押すと、文章が入った状態でXの投稿画面が開きます。<br>"
            f"開かないとき・文字が崩れるときは、下の「投稿文」をコピーして、Xに貼り付けてください。</p>"
            + (f"<p>※横動画のURLが取れなかったため、投稿文にURLは入っていません。</p>" if not url else "")
            + f"<p><a href=\"{intent}\" style=\"font-size:20px;font-weight:bold\">▶ Xの投稿画面を開く</a></p>"
            f"<p>▼投稿文(コピー用)</p><p style=\"white-space:pre-wrap;border:1px solid #ccc;padding:10px\">{esc(text)}</p>")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        print("::error::Gmailにログインできませんでした。GMAIL_APP_PASSWORD(16桁のアプリパスワード)が正しいか、2段階認証がオンか確認してください")
        return 1
    except Exception as e:
        print(f"::error::メールを送れませんでした: {type(e).__name__}: {e}")
        return 1
    os.makedirs(os.path.dirname(rec), exist_ok=True)
    jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    with open(rec, "w", encoding="utf-8") as f:
        json.dump({"to": to, "subject": subject, "at": jst}, f, ensure_ascii=False, indent=1)
    print(f"[mail] 送りました: {to}  件名={subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
