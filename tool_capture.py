#!/usr/bin/env python3
"""ツールの画面を、台本の順に操作して、場面ごとの画像を撮る(BOAT REX PRO ツール紹介ショート用)。
ツール本体(boat_scenario_pro.html と data/)があるフォルダを --tool で渡す。会員の状態で動かす(本番の公開サイトには触らない)。
公式サイトにはつなぎに行かない: /api/live は、渡した直前情報とオッズで答える(テスト版は仮の値)。
"""
import json, os, random, threading, http.server, socketserver, functools, itertools

VW, VH, DSF = 430, 860, 2.4          # 画面の大きさ(スマホ相当)と、撮影の細かさ
HILITE_JS = """(sel)=>{const e=document.querySelector(sel); if(!e) return false;
  e.scrollIntoView({block:'center'}); e.dataset._o=e.style.outline; e.style.outline='4px solid #ff3355'; e.style.outlineOffset='3px'; e.style.borderRadius='10px'; return true;}"""
UNHI_JS = """(sel)=>{const e=document.querySelector(sel); if(e){ e.style.outline=e.dataset._o||''; }}"""

MOVE_SPOKEN = {"先マイ": "先マイ", "抵抗": "抵抗", "2着残し": "2着残し", "3着残し": "3着残し", "凹み": "凹み",
               "壁追走": "壁追走", "差し": "差し", "直まくり": "直まくり", "まくり": "まくり", "まくり差し": "まくり差し",
               "絞りまくり": "絞りまくり", "外マイ": "外マイ", "最内差し": "最内差し", "展開突き（差し）": "展開突き"}
TABS = [("prob", "tabProb", "確率が高い、堅い買い目", "堅く"), ("hm", "tabHM", "確率が高めから中くらいの買い目", "バランスよく"),
        ("bal", "tabBal", "確率が中くらいの買い目", "中くらいの配当を"), ("ml", "tabML", "確率が中くらいから低めの買い目", "やや高めの配当を"),
        ("ev", "tabEv", "確率が低い、高配当の買い目", "高配当を")]


def serve(root, port):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    class Q(h.func):
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), functools.partial(Q, directory=root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def synth_odds(seed):
    """テスト用の仮のオッズ(120通り)。本番は、公式から取った本物の値に置き換える"""
    rnd = random.Random(seed)
    s = [rnd.uniform(.9, 1.1) * w for w in (.40, .17, .14, .12, .10, .07)]
    out = {}
    for a, b, c in itertools.permutations(range(6), 3):
        pa = s[a] / sum(s); pb = s[b] / (sum(s) - s[a]); pc = s[c] / (sum(s) - s[a] - s[b])
        out[f"{a+1}-{b+1}-{c+1}"] = round(min(999.9, max(1.5, rnd.uniform(0.62, 1.45) * 0.85 / (pa * pb * pc))), 1)
    return out


def synth_before(seed):
    rnd = random.Random(seed + 1)
    ex = [round(rnd.uniform(6.68, 6.86), 2) for _ in range(6)]
    return {"ok": True, "ex": ex, "tilt": [-0.5, -0.5, 0.0, -0.5, 0.0, 0.5], "wind": 2, "wave": 3, "windDir8": 3}


def capture(tool_dir, out_dir, venue, race_no, move_pos, move_name, tab_key, budget, seed, port=8765, live=None):
    """返す: 場面ごとの画像のリスト [{beat, files:[...]}] と、選んだ内容。失敗したら例外(固定値で埋めない)"""
    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    srv = serve(tool_dir, port)
    live = live or {"ok": True, "at": "(テスト用の仮の値)", "beforeinfo": synth_before(seed),
                    "odds": {"ok": True, "count": 120, "odds": synth_odds(seed)}}
    shots = {}
    def snap(beat, name, pg):
        p = os.path.join(out_dir, f"{beat:02d}_{name}.png")
        pg.screenshot(path=p)
        shots.setdefault(beat, []).append(p)
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--font-render-hinting=none"])
        ctx = br.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=DSF, has_touch=False, timezone_id="Asia/Tokyo", locale="ja-JP")
        pg = ctx.new_page()
        pg.route("**/api/live*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(live, ensure_ascii=False)))
        pg.route("**/api/hit*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"http://127.0.0.1:{port}/boat_scenario_pro.html")
        pg.wait_for_function("document.fonts.ready.then(()=>true)")
        pg.wait_for_timeout(1500)
        if not pg.evaluate("typeof BSP_MEMBER!=='undefined' && BSP_MEMBER"):
            raise RuntimeError("会員の状態で動いていません(meta bsp-mode)")
        def hi(sel, beat, name):
            if not pg.evaluate(HILITE_JS, sel): raise RuntimeError(f"画面に {sel} が見つかりません")
            pg.wait_for_timeout(250); snap(beat, name, pg); pg.evaluate(UNHI_JS, sel)
        # 1 ツールの最初の画面
        pg.evaluate("window.scrollTo(0,0)"); pg.wait_for_timeout(200); snap(1, "top", pg)
        # 2 レース場とレース番号(ツールに出ている、今日の開催場から、日付で決める)
        if not venue:
            vs = pg.evaluate("[...document.querySelectorAll('#track option')].map(o=>o.value).filter(v=>v)")
            if not vs: raise RuntimeError("レース場の選択肢がありません(今日の出走表がありません)")
            rr = random.Random(seed * 7 + 3); venue = rr.choice(vs); race_no = rr.randint(1, 12)
        hi("#track", 2, "a_track"); pg.select_option("#track", venue); pg.wait_for_timeout(250)
        hi("#raceNo", 2, "b_race"); pg.select_option("#raceNo", f"{race_no}R"); pg.wait_for_timeout(500)
        snap(2, "c_done", pg)
        # 3 直前情報
        hi("#infoAutoBtn", 3, "a_btn"); pg.click("#infoAutoBtn"); pg.wait_for_timeout(900)
        txt = pg.inner_text("#infoOk")
        if "展示タイム" not in txt: raise RuntimeError("直前情報が読み込めていません: " + txt[:80])
        pg.evaluate("document.querySelector('#infoOk').scrollIntoView({block:'center'})"); pg.wait_for_timeout(250); snap(3, "b_loaded", pg)
        # 4 スリット隊形(1艇を少し前に・1艇を少し後ろに)
        pg.evaluate("document.querySelector('#simSlitRow').scrollIntoView({block:'center'})"); pg.wait_for_timeout(300)
        snap(4, "a_before", pg)
        def drag(pos, to_idx):
            b = pg.locator(f"#simSlitBoat{pos}").bounding_box(); c = pg.locator(f"#simSlitCol{pos}").bounding_box()
            y1 = c["y"] + (118 / 4) * to_idx + 16
            pg.mouse.move(b["x"] + 14, b["y"] + 16); pg.mouse.down(); pg.mouse.move(b["x"] + 14, (b["y"] + y1) / 2, steps=4)
            pg.mouse.move(b["x"] + 14, y1, steps=4); pg.mouse.up(); pg.wait_for_timeout(350)
        drag(2, 0); drag(5, 4)
        snap(4, "b_after", pg)
        # 5 攻め筋(選んだコース・攻め筋)
        pg.evaluate("document.querySelector('#axisGrid').scrollIntoView({block:'center'})"); pg.wait_for_timeout(250)
        tiles = pg.locator("#axisGrid .axis-opt"); n = tiles.count()
        idx = [i for i in range(n) if pg.locator("#axisGrid .axis-opt .cpos").nth(i).inner_text() == f"{move_pos}コース"]
        if not idx: raise RuntimeError(f"{move_pos}コースの選択肢が画面にありません")
        tiles.nth(idx[0]).evaluate("e=>{e.style.outline='4px solid #ff3355';e.style.outlineOffset='3px'}"); pg.wait_for_timeout(200)
        snap(5, "a_tile", pg); tiles.nth(idx[0]).click(); pg.wait_for_timeout(500); snap(5, "b_modal", pg)
        btn = pg.locator("#modalMoveList .modal-move-btn", has_text=move_name).first
        if btn.count() == 0 or "disabled" in (btn.get_attribute("class") or ""): raise RuntimeError(f"{move_pos}コースの「{move_name}」は選べません")
        btn.evaluate("e=>{e.style.outline='4px solid #ff3355';e.style.outlineOffset='3px'}"); pg.wait_for_timeout(200); snap(5, "c_pick", pg)
        btn.click(); pg.wait_for_timeout(700)
        pg.evaluate("document.querySelector('#axisGrid').scrollIntoView({block:'center'})"); pg.wait_for_timeout(250); snap(5, "d_done", pg)
        # 6 確率帯
        tid = {k: i for k, i, *_ in TABS}[tab_key]
        hi("#" + tid, 6, "a_tab"); pg.click("#" + tid); pg.wait_for_timeout(300); snap(6, "b_done", pg)
        # 7 解析実行
        hi("#runBtn", 7, "a_btn"); pg.click("#runBtn"); pg.wait_for_timeout(1500)
        pg.evaluate("document.querySelector('#resultBody').scrollIntoView({block:'start'})"); pg.wait_for_timeout(300); snap(7, "b_result", pg)
        # 8 資金配分
        if not pg.is_visible("#fundOpenBtn"): raise RuntimeError("資金配分ボタンが出ていません")
        hi("#fundOpenBtn", 8, "a_btn"); pg.click("#fundOpenBtn"); pg.wait_for_timeout(600)
        pg.evaluate("document.querySelector('#budgetSelect').scrollIntoView({block:'center'})"); pg.wait_for_timeout(250); snap(8, "b_open", pg)
        # 9 予算とオッズ
        hi("#budgetSelect", 9, "a_budget"); pg.fill("#budgetSelect", str(budget)); pg.dispatch_event("#budgetSelect", "change"); pg.wait_for_timeout(300)
        snap(9, "b_budget", pg)
        hi("#oddsAutoBtn", 9, "c_btn"); pg.click("#oddsAutoBtn"); pg.wait_for_timeout(1500)
        # 10 配分された買い目
        pg.evaluate("document.querySelector('#fundRow').scrollIntoView({block:'start'})"); pg.wait_for_timeout(400); snap(10, "a_result", pg)
        pg.evaluate("window.scrollBy(0, 520)"); pg.wait_for_timeout(300); snap(10, "b_result2", pg)
        info = {"venue": venue, "no": race_no, "bets": pg.evaluate("document.querySelector('#totalStake') ? document.querySelector('#totalStake').innerText : ''"),
                "pageerrors": errs}
        br.close()
    srv.shutdown()
    return shots, info


if __name__ == "__main__":
    import sys
    tool = sys.argv[1]
    shots, info = capture(tool, "cap_out", "江戸川", 1, 1, "先マイ", "ev", 10000, 1)
    print({k: len(v) for k, v in shots.items()}, info)
