"""
summary_mail.py
summary/日付.json(非公開側が送ってくる5帯の集計)から、メールを作って送る。
  ・その日の表(5帯 × 購入点数・投資金額・回収金額・回収率)
  ・これまでの累計の表(summary/ に入っている、答え合わせのある日の合計)
全買い目を、1点100円ずつ買った場合の集計。
使い方: python summary_mail.py --date YYYYMMDD [--dry-run] [--force]
  --dry-run  送らずに、本文を表示するだけ
  --force    送信済みの日でも、もう一度送る
送信済みの記録: uploaded/日付_summary_mail.json(同じ日を2通送らない)
環境変数: MAIL_USER, MAIL_TO, GMAIL_APP_PASSWORD
"""
import argparse
import glob
import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

BANDS = ["prob", "hm", "bal", "ml", "ev"]


def load_all(upto):
    days = []
    for f in sorted(glob.glob("summary/*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if d["date"] <= upto and d.get("races_checked", 0) > 0:
            days.append(d)
    return days


def total(days):
    t = {k: {"label": "", "points": 0, "payout": 0} for k in BANDS}
    for d in days:
        for b in d["bands"]:
            x = t[b["key"]]
            x["label"] = b["label"]
            x["points"] += b["points"]
            x["payout"] += b["payout"]
    rows = []
    for k in BANDS:
        x = t[k]
        stake = x["points"] * 100
        rows.append((x["label"], x["points"], stake, x["payout"], round(x["payout"] / stake * 100, 1) if stake else 0.0))
    return rows


def day_rows(d):
    return [(b["label"], b["points"], b["stake"], b["payout"], b["roi"]) for b in d["bands"]]


def fmt_date(s):
    return f"{int(s[4:6])}/{int(s[6:8])}"


def text_table(rows):
    out = ["帯 / 購入点数 / 投資金額 / 回収金額 / 回収率"]
    for l, p, s, y, r in rows:
        out.append(f"{l} / {p:,}点 / {s:,}円 / {y:,}円 / {r}%")
    return "\n".join(out)


def html_table(rows):
    h = ['<table style="border-collapse:collapse;font-size:14px">',
         '<tr style="background:#eee">' + "".join(f'<th style="border:1px solid #bbb;padding:6px 10px;text-align:{a}">{t}</th>' for t, a in
                                                  [("帯", "left"), ("購入点数", "right"), ("投資金額", "right"), ("回収金額", "right"), ("回収率", "right")]) + "</tr>"]
    for l, p, s, y, r in rows:
        color = "#c00" if r < 100 else "#080"
        h.append("<tr>" + f'<td style="border:1px solid #bbb;padding:6px 10px">{escape(l)}</td>'
                 f'<td style="border:1px solid #bbb;padding:6px 10px;text-align:right">{p:,}点</td>'
                 f'<td style="border:1px solid #bbb;padding:6px 10px;text-align:right">{s:,}円</td>'
                 f'<td style="border:1px solid #bbb;padding:6px 10px;text-align:right">{y:,}円</td>'
                 f'<td style="border:1px solid #bbb;padding:6px 10px;text-align:right;color:{color}"><b>{r}%</b></td></tr>')
    h.append("</table>")
    return "\n".join(h)


def build(date):
    d = json.load(open(f"summary/{date}.json", encoding="utf-8"))
    days = load_all(date)
    cum = total(days)
    n_races = sum(x["races_checked"] for x in days)
    span = f"{fmt_date(days[0]['date'])}〜{fmt_date(days[-1]['date'])}の{len(days)}日分・{n_races}レース" if days else ""
    subject = f"【BOAT REX PRO】{fmt_date(date)} 5帯の集計(全買い目100円ずつ)"
    head = f"全買い目を1点100円ずつ購入した場合の集計です。対象: {d.get('scope','')}・{d['races_checked']}レース(答え合わせできなかった{d['races_excluded']}レースは除く)。"
    txt = f"{head}\n\n■{fmt_date(date)}の分\n{text_table(day_rows(d))}\n\n■累計({span})\n{text_table(cum)}\n"
    html = (f"<p>{escape(head)}</p><h3>{fmt_date(date)}の分</h3>{html_table(day_rows(d))}"
            f"<h3>累計({escape(span)})</h3>{html_table(cum)}"
            f"<p style=\"color:#666;font-size:12px\">累計は、非公開側から集計が届いた日(答え合わせのある日)の合計です。</p>")
    return subject, txt, html


def send(subject, txt, html):
    user = os.environ["MAIL_USER"]
    to = os.environ["MAIL_TO"]
    pw = "".join(os.environ["GMAIL_APP_PASSWORD"].split())
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(txt, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    date = a.date
    if not date:
        fs = sorted(os.path.basename(f)[:-5] for f in glob.glob("summary/*.json"))
        if not fs:
            print("summary/ に集計がありません")
            return 1
        date = fs[-1]
    if not os.path.exists(f"summary/{date}.json"):
        print(f"summary/{date}.json がありません")
        return 1
    mark = f"uploaded/{date}_summary_mail.json"
    subject, txt, html = build(date)
    if a.dry_run:
        print(subject + "\n\n" + txt)
        return 0
    if os.path.exists(mark) and not a.force:
        print(f"{date} は送信済みです。送りません(送り直すときは force)")
        return 0
    send(subject, txt, html)
    os.makedirs("uploaded", exist_ok=True)
    json.dump({"date": date, "subject": subject}, open(mark, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{date}: メールを送りました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
