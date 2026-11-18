#!/usr/bin/env python3
"""出走表サイト(BOAT REX PRO オリジナル出走表)の画面を、台本の順に撮る(出走表サイト紹介ショート用)。
流れ: トップ画面 → グレードが一番高い場を選ぶ → その場の最終レースの出走表 → 説明する欄を切り出す。
  ・公式サイトには行かない。行くのは、自分たちの出走表サイト(--base)だけ。
  ・サイトの来場者の数字が増えないよう、数えるための通信(/api/hit・Cloudflareの計測)は止めて撮る。
  ・欄の切り出しは、画面の表(.hd の見出しと .row の6行)の位置から計算する。見つからなければ、固定値で埋めずに止まる。
"""
import os, random, re
from urllib.parse import urljoin
from PIL import Image

GRADE_ORDER = ["SG", "G1", "G2", "G3"]
DSF = 2
RED = "#ff3355"

# 出走表の列の番号(見出し .hd の子と、各 .row の子は同じ並び)
C_WAKU, C_NAME, C_FLST, C_MAVG, C_NAT, C_LOC, C_MOTOR, C_BOAT, C_TENJI, C_KG, C_R10, C_DAY = range(12)

JS_RECTS = """(n)=>{const rc=document.querySelector('#rc'+n); if(!rc) return null;
  const hd=rc.querySelector('.hd'); const rows=[...rc.querySelectorAll('.row')]; if(!hd||rows.length<2) return null;
  const r=e=>{const b=e.getBoundingClientRect();return {x:b.x+scrollX,y:b.y+scrollY,w:b.width,h:b.height}};
  return {txt:[...hd.children].map(e=>e.textContent.replace(/\\s+/g,'')), hd:[...hd.children].map(r), rows:rows.map(row=>[...row.children].map(r))}}"""
JS_OUTLINE = """([n,sel,rowsMax])=>{const rc=document.querySelector('#rc'+n); let k=0;
  [...rc.querySelectorAll('.row')].slice(0,rowsMax).forEach(row=>{row.querySelectorAll(sel).forEach(e=>{e.dataset._o=e.style.outline;e.style.outline='3px solid %s';e.style.outlineOffset='2px';k++})}); return k}""" % RED
JS_OUTLINE_CELL = """([n,col,rowsMax])=>{const rc=document.querySelector('#rc'+n);
  [...rc.querySelectorAll('.row')].slice(0,rowsMax).forEach(row=>{const e=row.children[col]; e.dataset._o=e.style.outline;e.style.outline='4px solid %s';e.style.outlineOffset='-3px'})}""" % RED
JS_UNOUTLINE = """()=>{document.querySelectorAll('[data-_o]').forEach(e=>{e.style.outline=e.dataset._o||'';e.removeAttribute('data-_o')})}"""


def _runs(cols):
    out = []
    for c in sorted(cols):
        if out and c == out[-1][-1] + 1: out[-1].append(c)
        else: out.append([c])
    return out


def pick_card(cards, seed):
    """グレード(SG>G1>G2>G3)が一番高い場。同じグレードが複数なら、日付で決める。グレードの場が1つもなければ、開催中の場から日付で決める"""
    def rk(c): return GRADE_ORDER.index(c["grade"]) if c["grade"] in GRADE_ORDER else 99
    best = min(rk(c) for c in cards)
    top = [c for c in cards if rk(c) == best]
    return random.Random(seed * 17 + 3).choice(top)


def capture(base, out_dir, date, seed, check_date=True, log=print):
    """返す: (shots, info)。shots = {名前: 画像のパス}、info = {venue, no, grade, href}。失敗したら例外(固定値で埋めない)"""
    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    base = base.rstrip("/") + "/"
    mm, dd = int(date[4:6]), int(date[6:8])
    shots = {}
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--font-render-hinting=none"])
        def newpage(w):
            ctx = br.new_context(viewport={"width": w, "height": 1000}, device_scale_factor=DSF, locale="ja-JP", timezone_id="Asia/Tokyo")
            pg = ctx.new_page()
            pg.route("**/api/hit*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
            pg.route("**/*cloudflareinsights.com/**", lambda r: r.abort())
            return pg
        # ---- トップ画面 ----
        pg = newpage(1200)
        pg.goto(base, wait_until="load", timeout=60000)
        pg.wait_for_function("document.fonts.ready.then(()=>true)"); pg.wait_for_timeout(1200)
        cards = pg.evaluate("""[...document.querySelectorAll('a.vc')].map(a=>({href:a.getAttribute('href'),
            grade:((a.querySelector('.bg')||{}).textContent||'').trim(), name:a.querySelector('.nm').textContent.trim()}))""")
        if not cards: raise RuntimeError("トップ画面に、開催中の場がありません(a.vc が0個)")
        top_txt = pg.inner_text("body")
        today_ok = f"{mm}月{dd}日" in top_txt
        card = pick_card(cards, seed)
        log(f"[場] 開催 {len(cards)}場 / 選んだ場: {card['name']}({card['grade'] or 'グレードなし'}) / トップ画面に「{mm}月{dd}日」: {'あり' if today_ok else 'なし'}")
        p1 = os.path.join(out_dir, "01_top.png"); pg.screenshot(path=p1, clip={"x": 0, "y": 0, "width": 1200, "height": 1000}); shots["top"] = p1
        ok = pg.evaluate("""(href)=>{const a=[...document.querySelectorAll('a.vc')].find(x=>x.getAttribute('href')===href); if(!a) return false;
            a.style.outline='5px solid %s'; a.style.outlineOffset='3px'; a.style.borderRadius='6px'; return true}""" % RED, card["href"])
        if not ok: raise RuntimeError("選んだ場のカードが見つかりません")
        box = pg.evaluate("""()=>{const g=document.querySelector('.vg'); if(!g) return null; const b=(g.parentElement||g).getBoundingClientRect(); return {x:b.x+scrollX,y:b.y+scrollY,width:b.width,height:b.height}}""")
        if not box: raise RuntimeError("場の一覧(.vg)が見つかりません")
        p2 = os.path.join(out_dir, "02_grid.png"); pg.screenshot(path=p2, clip=box, full_page=True); shots["grid"] = p2
        pg.context.close()
        # ---- 場のページ ----
        pg = newpage(1782)
        pg.goto(urljoin(base, card["href"]), wait_until="load", timeout=60000)
        pg.wait_for_function("document.fonts.ready.then(()=>true)"); pg.wait_for_timeout(1200)
        if check_date and not today_ok and f"{mm}月{dd}日" not in pg.inner_text("body"):
            raise RuntimeError(f"今日({mm}月{dd}日)の出走表ではありません(トップ画面にも場のページにも日付がありません)。サイトの更新前かもしれません")
        ids = pg.evaluate("[...document.querySelectorAll('.rc')].map(e=>parseInt(e.id.replace('rc','')))")
        if not ids: raise RuntimeError("レースがありません(.rc が0個)")
        n = max(ids)
        pg.evaluate("(n)=>{location.hash='#r'+n}", n); pg.wait_for_timeout(700)
        if pg.evaluate("(n)=>getComputedStyle(document.querySelector('#rc'+n)).display", n) == "none":
            raise RuntimeError(f"{n}Rの出走表が表示されません")
        title = pg.inner_text(f"#rc{n} .rt").replace("← スワイプ", "").strip()
        log(f"[レース] {card['name']} {n}R({title})")
        H = int(pg.evaluate("document.documentElement.scrollHeight")) + 40       # ページ全体が画面に入る高さにする(切り出しが、ページの座標のまま使える)
        pg.set_viewport_size({"width": 1782, "height": min(H, 6000)}); pg.wait_for_timeout(500)
        pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(200)
        R = pg.evaluate(JS_RECTS, n)
        if not R or len(R["hd"]) < 11 or len(R["rows"]) < 6 or any(len(x) < 11 for x in R["rows"]):
            raise RuntimeError(f"出走表の表の形が想定と違います(見出し {len(R['hd']) if R else 0}列・行 {len(R['rows']) if R else 0})")
        # 列の並びが変わっていないかを、見出しの文字で確かめる(違えば、違う欄を切り出さないよう止まる)
        expect = {C_NAME: "BOATREXPROランク", C_FLST: "平均ST", C_NAT: "全国", C_LOC: "当地", C_MOTOR: "モーター", C_BOAT: "ボート", C_KG: "BOATREXPROデータ", C_R10: "直近10走"}
        bad = [f"{i}列目(想定「{w}」/実際「{R['txt'][i][:14]}」)" for i, w in expect.items() if w not in R["txt"][i]]
        if bad: raise RuntimeError("出走表の列の並びが想定と違います: " + "、".join(bad))

        def grab(name, cols, rows_n=6, outline_sel=None, outline_cells=None):
            """出走表の列(見出し+指定の行数)を切り出して、横に並べた1枚の画像にする"""
            pg.evaluate(JS_UNOUTLINE)
            k = pg.evaluate(JS_OUTLINE, [n, outline_sel, rows_n]) if outline_sel else None
            if outline_cells: pg.evaluate(JS_OUTLINE_CELL, [n, outline_cells, rows_n])
            y0 = R["hd"][0]["y"]; last = R["rows"][rows_n - 1][0]; y1 = last["y"] + last["h"]
            parts = []
            for run in _runs(cols):
                x0 = R["hd"][run[0]]["x"]; x1 = R["hd"][run[-1]]["x"] + R["hd"][run[-1]]["w"]
                pth = os.path.join(out_dir, f"_{name}_{run[0]}.png")
                pg.screenshot(path=pth, clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
                parts.append(Image.open(pth).convert("RGB"))
            pg.evaluate(JS_UNOUTLINE)
            gap = 10
            W = sum(i.width for i in parts) + gap * (len(parts) - 1); Hh = max(i.height for i in parts)
            canvas = Image.new("RGB", (W, Hh), (203, 213, 225)); x = 0
            for i in parts: canvas.paste(i, (x, 0)); x += i.width + gap
            out = os.path.join(out_dir, f"{name}.png"); canvas.save(out); shots[name] = out
            return k

        def element(name, sel, narrow=None):
            pth = os.path.join(out_dir, f"{name}.png")
            if narrow:        # 横に長い欄(特徴)は、複製を細くして改行させる(撮影の間だけ。サイトの表示は変えない)
                pg.evaluate("""([sel,w])=>{const e=document.querySelector(sel); if(!e) throw new Error('no '+sel); const c=e.cloneNode(true);
                    c.style.cssText+=';width:'+w+'px;box-sizing:border-box;margin:0'; const wr=document.createElement('div'); wr.id='_clone';
                    wr.style.cssText='position:absolute;left:0;top:0;z-index:2147483647;background:#fff;padding:8px;width:'+(w+16)+'px'; wr.appendChild(c); document.body.appendChild(wr); wr.style.height=(c.getBoundingClientRect().height+16)+'px'; wr.style.overflow='hidden'}""", [sel, narrow])
                rc_ = pg.evaluate("""()=>{const b=document.querySelector('#_clone > *').getBoundingClientRect(); return {x:b.x+scrollX-6,y:b.y+scrollY-6,width:b.width+12,height:b.height+12}}""")
                pg.screenshot(path=pth, clip=rc_); pg.evaluate("document.getElementById('_clone').remove()")
            else:
                loc = pg.locator(sel).first
                if loc.count() == 0: raise RuntimeError(f"画面に {sel} が見つかりません")
                loc.screenshot(path=pth)
            shots[name] = pth

        # 2: ごらんのメンバー(枠・名前・F/L/ST・節間平均ST)
        grab("members", [C_WAKU, C_NAME, C_FLST, C_MAVG])
        # 3: 場の話(4種)
        element("venue_fx", ".fx", narrow=760); element("venue_pc", ".pc"); element("venue_pk", ".pk"); element("venue_pd", ".pd")
        # 4: 1号艇・2号艇の BOAT REX PRO データ(逃げ率・差され率・まくられ率 / 逃がし率)
        grab("kg_1", [C_WAKU, C_KG], rows_n=1, outline_cells=C_KG)
        grab("kg_12", [C_WAKU, C_KG], rows_n=2, outline_cells=C_KG)
        # 5: 選手の話(6種)
        grab("p_rank", [C_WAKU, C_NAME], outline_sel=".rk")
        grab("p_st", [C_WAKU, C_FLST], outline_sel=".sc")
        grab("p_waku", [C_WAKU, C_NAT, C_LOC])
        grab("p_motor", [C_WAKU, C_MOTOR, C_BOAT])
        grab("p_r10", [C_WAKU, C_R10])
        if not grab("p_nige2", [C_WAKU, C_KG], rows_n=1, outline_sel=".sec"):
            raise RuntimeError("1号艇の「逃げた時の2着」の欄(.sec)が見つかりません")
        has_rk = pg.evaluate("document.querySelectorAll('#rc%d .row .nm .rk').length" % n) > 0       # 勝率ランクのバッジが1人でもいるか
        has_sc = pg.evaluate("[...document.querySelectorAll('#rc%d .row')].some(r=>{const s=r.children[2].querySelector('.sc'); return s && !s.classList.contains('sx')})" % n)
        log(f"[使える題材] 勝率ランク: {'あり' if has_rk else 'なし'} / STランク: {'あり' if has_sc else 'なし'}")
        br.close()
    return shots, {"venue": card["name"], "no": n, "grade": card["grade"], "href": card["href"], "race_title": title, "has_rk": bool(has_rk), "has_sc": bool(has_sc)}
