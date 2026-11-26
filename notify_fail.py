# -*- coding: utf-8 -*-
"""
失敗したことを、REXにメールで知らせる(標準の部品だけ。秘密の値は、環境変数で受け取る)。
環境変数: MAIL_USER, MAIL_TO, GMAIL_APP_PASSWORD, WORKFLOW_NAME, RUN_URL, NOTE
メールが送れなくても、実行は失敗にしない(終了コード0)。
"""
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

JST = timezone(timedelta(hours=9))


def main():
    pw = "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split())
    user = os.environ.get("MAIL_USER", "")
    to = os.environ.get("MAIL_TO", "")
    if not (pw and user and to):
        print("::warning::メールの設定が足りないため、失敗の知らせは送れませんでした")
        return 0
    name = os.environ.get("WORKFLOW_NAME", "自動実行")
    url = os.environ.get("RUN_URL", "")
    note = os.environ.get("NOTE", "")
    now = datetime.now(JST).strftime("%m月%d日 %H:%M")
    body = (
        f"BOAT REX PRO の自動実行が、失敗しました。\n\n"
        f"・どれ: {name}\n・いつ: {now}\n"
        f"・失敗した実行のページ(ここを開くと、赤い文が見られます):\n{url}\n\n"
        f"{note}\n\n"
        f"このメールは、失敗したときだけ届きます。\n"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"【失敗】{name}"
    msg["From"] = user
    msg["To"] = to
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        print("失敗の知らせを、メールで送りました")
    except Exception as e:  # メールの失敗で、実行をさらに赤くしない
        print(f"::warning::失敗の知らせのメールを送れませんでした: {type(e).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
