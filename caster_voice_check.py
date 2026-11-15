#!/usr/bin/env python3
"""4人のキャスターの声が、VOICEVOXに入っていて、実際に音が出るかを確かめる(GitHubのテスト用)。
  1人でも出せなければ、赤(失敗)で終わる。実行ページの「Summary」に、結果の一覧と、利用できる声の一覧を出す。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

import casters

URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")
TEXT = "ボートレックスプロ答え合わせの時間です。"


def get(path):
    with urllib.request.urlopen(URL + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(URL + path, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def main():
    sp = get("/speakers")
    rows, bad = [], 0
    for c in casters.CASTERS:
        sid = casters.find_style_id(sp, c)
        if sid is None:
            have = [f"{'/'.join(st['name'] for st in s['styles'])}" for s in sp if s["name"] == c["voice"]]
            why = f"スタイルが見つかりません(この声のスタイル: {have[0]})" if have else "この声が一覧にありません"
            rows.append((c["id"], c["voice"], "/".join(c["styles"]), "NG", why))
            bad += 1
            continue
        try:
            q = json.loads(post(f"/audio_query?text={urllib.parse.quote(TEXT)}&speaker={sid}"))
            wav = post(f"/synthesis?speaker={sid}", q)
            ok = len(wav) > 1000 and wav[:4] == b"RIFF"
            rows.append((c["id"], c["voice"], "/".join(c["styles"]), "OK" if ok else "NG",
                         f"番号 {sid}・音声 {len(wav) / 1000:.0f}KB" if ok else "音が出ませんでした"))
            bad += 0 if ok else 1
        except Exception as e:
            rows.append((c["id"], c["voice"], "/".join(c["styles"]), "NG", f"合成に失敗: {type(e).__name__}: {e}"))
            bad += 1
    lines = ["### キャスター4人の声の確認", "", "| 人 | 声 | スタイル | 結果 | 内容 |", "|---|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c_} | {d} | {e} |" for a, b, c_, d, e in rows]
    lines += ["", "<details><summary>VOICEVOXで利用できる声の一覧</summary>", ""]
    lines += [f"- {s['name']}({'/'.join(st['name'] for st in s['styles'])})" for s in sp]
    lines += ["", "</details>", ""]
    text = "\n".join(lines)
    print(text)
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    if bad:
        print(f"::error title=声の確認に失敗::{bad}人の声が使えません。上の表を確認してください")
        return 1
    print("::notice title=声の確認::4人とも、声が出ました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
