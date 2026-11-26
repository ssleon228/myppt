"""排版求解：积木结构 → 每个元素的坐标和字号档位，并给出质量报告。

做法（全部是程序规则，不依赖模型）：
1. 字号档位从大到小试（0..6），取「整页放得下」的最大档 —— 字少就放大填满，字多就缩小，缩到底还放不下就判失败。
2. 行：宽度按 w 分；没写 w 时，同类元素等宽，不同类按内容量自动分（内容多的栏宽一些，左右高度接近）。
3. 列：元素按自身高度从上往下排；剩余空间先给图表/图片，再让卡片适度长高，再加大间距，最后整体垂直居中。
4. 质量检查：溢出、留白（填充率）、左右不平衡、字被压得太小、元素太多。
"""
from . import blocks as B
from .tokens import GAP, PAD, LEVELS, BASE_LEVEL, AREA

TOP_BAR = 6
LEFT_BAR = 6


def _pads(n):
    """→ (左, 上, 右, 下) 内边距"""
    st = n.get("style", "none")
    if st == "none":
        return 0, 0, 0, 0
    if st == "leftbar":
        return 30, 2, 0, 2
    p = PAD[n.get("pad", "m")]
    if st == "topbar":
        return p, p + TOP_BAR, p, p
    if st == "rule":  # 杂志风：只有顶部细线
        return 0, 26, 0, 6
    if st in ("panel", "panel-light"):  # 通栏侧板：内边距大一些
        return p + 12, p + 12, p + 12, p + 12
    if st == "fine":  # 典雅细框：留白更多
        return p + 8, p + 8, p + 8, p + 8
    return p, p, p, p


def is_flex(n):
    return "el" in n and n["el"] in B.FLEX


class Solver:
    def __init__(self, tree):
        if tree.get("box") == "row" or "el" in tree:  # 顶层是一排卡片时也要走「列」的长高 / 居中规则，否则卡片被拉满整页
            tree = {"box": "col", "children": [tree], "gap": "m", "style": "none", "pad": "m", "align": "start"}
        self.tree = tree
        self._cache = {}

    # ── 宽度分配 ──
    def widths(self, n, w, L):
        kids = n["children"]
        gap = GAP[n.get("gap", "m")]
        avail = w - gap * (len(kids) - 1)
        explicit = [c.get("w") for c in kids]
        if any(v is not None for v in explicit):
            ws = [v if v is not None else 1.0 for v in explicit]
        else:
            ws = self.auto_weights(kids, avail, L)
        tot = sum(ws) or 1
        return [avail * v / tot for v in ws], gap

    def auto_weights(self, kids, avail, L):
        from .spec import signature
        sigs = set(signature(c) for c in kids if not (c.get("el") == "spacer"))
        if len(sigs) <= 1:
            return [1.0] * len(kids)
        eq = avail / len(kids)
        areas = []
        for c in kids:
            if is_flex(c) or (c.get("el") == "table"):
                areas.append(None)
            else:
                areas.append(max(1.0, self.natural(c, eq, L)) * eq)
        known = [a for a in areas if a]
        mean = (sum(known) / len(known)) if known else 1.0
        ws = []
        for a in areas:
            if a is None:
                ws.append(1.5)
            else:
                ws.append(max(0.6, min(1.7, (a / mean) ** 0.7)))
        return ws

    # ── 自然高度 ──
    def natural(self, n, w, L):
        key = (id(n), int(w), L)
        if key in self._cache:
            return self._cache[key]
        l, t, r, b = _pads(n)
        iw = w - l - r
        if "el" in n:
            h = B.MEASURE[n["el"]](n, iw, L)
        elif n["box"] == "row":
            ws, _ = self.widths(n, iw, L)
            h = max(self.natural(c, cw, L) for c, cw in zip(n["children"], ws))
        else:
            gap = GAP[n.get("gap", "m")]
            h = sum(self.natural(c, iw, L) for c in n["children"]) + gap * (len(n["children"]) - 1)
        h += t + b
        self._cache[key] = h
        return h

    # ── 放置 ──
    def place(self, n, x, y, w, h, L, tone, out, depth=0):
        st = n.get("style", "none")
        if st != "none":
            out["cards"].append((st, (x, y, w, h)))
            if st in ("accent", "dark", "block", "panel"):
                tone = "dark"
        l, t, r, b = _pads(n)
        x, y, w, h = x + l, y + t, w - l - r, h - t - b
        if "el" in n:
            out["leaves"].append((n, (x, y, w, h), tone, B.MEASURE[n["el"]](n, w, L)))
            return
        kids = n["children"]
        if n["box"] == "row":
            ws, gap = self.widths(n, w, L)
            nats = [self.natural(c, cw, L) for c, cw in zip(kids, ws)]
            out["rows"].append((nats, h, [c for c in kids]))
            if n.get("seq"):
                bx, cx0 = [], x
                for cw in ws:
                    bx.append((cx0, y, cw, h))
                    cx0 += cw + gap
                out.setdefault("seq", []).append(bx)
            cx = x
            for c, cw in zip(kids, ws):
                self.place(c, cx, y, cw, h, L, tone, out, depth + 1)
                cx += cw + gap
            return
        gap = GAP[n.get("gap", "m")]
        nats = [self.natural(c, w, L) for c in kids]
        free = h - sum(nats) - gap * (len(kids) - 1)
        if free < -1:
            out["overflow"] = max(out["overflow"], -free)
            free = 0
        hs = list(nats)
        # ① 图表 / 图片 / 留白 吃掉剩余空间
        flex = [i for i, c in enumerate(kids) if is_flex(c)]
        if flex and free > 0:
            per = free / len(flex)
            for i in flex:
                hs[i] += per
            free = 0
        # ② 表格行高、卡片（或一行卡片）适度长高：表格最多 +40%，卡片最多 +15%（再多就是空卡片）
        if free > 0:
            cap = {"table": 0.9, "flow": 0.9, "timeline": 0.7, "orbs": 0.6}
            grow = [(i, cap.get(c.get("el"), 0.15)) for i, c in enumerate(kids)
                    if self._card_like(c) or c.get("el") in cap]
            if grow:
                want = sum(nats[i] * cap for i, cap in grow)
                k = min(1.0, free / want) if want else 0
                for i, cap in grow:
                    add = nats[i] * cap * k
                    hs[i] += add
                    free -= add
        # 结论条贴底：顶层最后一个是结论条时，它固定放在内容区底部，剩余空间留在它上面
        anchor = depth == 0 and len(kids) > 1 and kids[-1].get("el") == "callout"
        body = kids[:-1] if anchor else kids
        # ③ 加大间距（最多到 2.5 倍）
        g = gap
        if free > 0 and len(body) > 1 and n.get("align") != "center":
            extra = min(free / (len(body) - 1), gap * 1.5 if n.get("align") != "spread" else gap * 3)
            g = gap + extra
            free -= extra * (len(body) - 1)
        # ④ 剩余：顶层垂直居中（略偏上），内层靠上；有贴底结论条时内容靠上、结论条贴底
        cy = y
        if anchor:
            for c, ch in zip(body, hs):
                self.place(c, x, cy, w, ch, L, tone, out, depth + 1)
                cy += ch + g
            self.place(kids[-1], x, y + h - hs[-1], w, hs[-1], L, tone, out, depth + 1)
            return
        if free > 0 and (depth == 0 or n.get("align") == "center"):
            cy += free * (0.42 if depth == 0 else 0.5)
        for c, ch in zip(kids, hs):
            self.place(c, x, cy, w, ch, L, tone, out, depth + 1)
            cy += ch + g

    def _card_like(self, c):
        if c.get("style", "none") != "none":
            return True
        if c.get("box") == "row":
            return all(k.get("style", "none") != "none" or k.get("el") == "spacer" for k in c["children"])
        return False

    # ── 求解 ──
    def solve(self, area=None, max_level=None):
        a = area or AREA
        top = len(LEVELS) - 1 if max_level is None else max_level
        level = None
        for L in range(top, -1, -1):
            if self.natural(self.tree, a["w"], L) <= a["h"] + 0.5:
                level = L
                break
        if level is None:
            return {"ok": False, "level": 0, "reason": "overflow",
                    "need": self.natural(self.tree, a["w"], 0), "avail": a["h"], "leaves": [], "cards": []}
        out = {"leaves": [], "cards": [], "rows": [], "overflow": 0.0}
        self.place(self.tree, a["x"], a["y"], a["w"], a["h"], level, "light", out)
        out["ok"] = out["overflow"] <= 1
        out["level"] = level
        out["natural"] = self.natural(self.tree, a["w"], level)
        out["area"] = a
        out["report"] = quality(out, a)
        return out


def quality(res, a):
    """质量报告：fill 填充率、level 字号档、warnings"""
    warns = []
    area = float(a["w"] * a["h"])
    ink = 0.0
    card_boxes = [b for _, b in res["cards"]]

    def inside(box):
        x, y, w, h = box
        for cx, cy, cw, ch in card_boxes:
            if x >= cx - 1 and y >= cy - 1 and x + w <= cx + cw + 1 and y + h <= cy + ch + 1:
                return True
        return False

    for _, (x, y, w, h) in res["cards"]:
        ink += w * h * 0.25  # 卡片底色有一定视觉分量，但空卡片不算填满
    card_content = {}
    for n, (x, y, w, h), tone, nat in res["leaves"]:
        if n["el"] == "spacer":
            continue
        if B.FLEX.get(n["el"]) is not None:
            ink += w * h
            continue
        ink += w * min(h, nat) * B.use_ratio(n, w, res["level"]) * (0.75 if inside((x, y, w, h)) else 1.0)
        for i, (cx, cy, cw, ch) in enumerate(card_boxes):
            if x >= cx - 1 and y >= cy - 1 and x + w <= cx + cw + 1 and y + h <= cy + ch + 1:
                card_content[i] = card_content.get(i, 0) + nat
    empty = 0
    for i, (cx, cy, cw, ch) in enumerate(card_boxes):
        if ch > 220 and card_content.get(i, 0) < ch * 0.5:
            empty += 1
    if empty:
        warns.append(("card-empty", "%d 张卡片里内容不到一半高度" % empty))
    fill = min(1.0, ink / area)
    vfill = res["natural"] / float(a["h"])
    if fill < 0.38:
        warns.append(("sparse", "页面偏空（内容只占 %d%%）" % round(fill * 100)))
    if res["level"] < BASE_LEVEL:
        warns.append(("dense", "文字偏多，字号被压到第 %d 档（基准 %d 档）" % (res["level"], BASE_LEVEL)))
    for nats, h, kids in res["rows"]:
        if len(nats) < 2 or h < 260:
            continue
        real = [v for v, c in zip(nats, kids) if not is_flex(c) and c.get("el") != "spacer"
                and c.get("style", "none") == "none"]
        if len(real) >= 2 and min(real) < max(real) * 0.45:
            warns.append(("imbalance", "并排的几栏内容量差太多（%d / %d px）" % (min(real), max(real))))
    # 大片空白带：竖向上没有任何内容 / 卡片覆盖的最长一段（看起来就是"半页空着"）
    spans = [(y, y + h) for _, (x, y, w, h) in res["cards"]]
    for n, (x, y, w, h), tone, nat in res["leaves"]:
        if n["el"] == "spacer":
            continue
        full = B.FLEX.get(n["el"]) is not None or (n["el"] in ("flow", "timeline") and h - nat > 60)
        if n["el"] == "table":
            h = min(h, nat * 1.9)
            full = True
        if n["el"] == "orbs":
            u = B.orbs_used(n, w, h, res["level"])
            y += max(0.0, (h - u) * 0.35)
            spans.append((y, y + u))
            continue
        spans.append((y, y + (h if full else min(h, nat))))
    spans.sort()
    gap_max, cur = 0.0, a["y"]
    for y0, y1 in spans:
        gap_max = max(gap_max, y0 - cur)
        cur = max(cur, y1)
    gap_max = max(gap_max, a["y"] + a["h"] - cur)
    band = gap_max / float(a["h"])
    if band > 0.2:
        warns.append(("blank-band", "有一整条空白带（%d%% 页高）" % round(band * 100)))
    nleaves = len([1 for n, *_ in res["leaves"] if n["el"] != "spacer"])
    if nleaves > 12:
        warns.append(("crowded", "元素 %d 个，偏多" % nleaves))
    return {"fill": round(fill, 3), "band": round(band, 3), "vfill": round(vfill, 3), "level": res["level"], "warnings": warns}


def _width_use(n, w):
    """文字元素实际占用的宽度比例（一行短字放在很宽的框里，不算填满）"""
    from . import measure as M
    from .tokens import size
    if n["el"] in ("text", "heading", "callout"):
        txt = n.get("text") or ""
        role = n.get("role") or ("h2" if n["el"] == "heading" else "body")
        try:
            one = M.text_w(txt, size(role if role in ("h1", "h2", "lead", "body", "small") else "body", BASE_LEVEL))
        except Exception:  # noqa: BLE001
            return 1.0
        return max(0.25, min(1.0, one / max(1.0, w)))
    return 1.0
