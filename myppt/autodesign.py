"""程序自己当设计师：按页型和内容量，生成几种候选版面（积木结构），交给求解器打分挑最好的。

AI 没给 layout、或给的 layout 不合格时用它。所以不管哪个模型来写内容，版面底线一样。
每个候选只是一种「搭法」，字号、宽度、间距都由求解器按内容算，不在这里写死。
"""


def _s(v):
    return "" if v is None else str(v).strip()


def _texts(items):
    out = []
    for it in items or []:
        if isinstance(it, dict):
            t = _s(it.get("text") or it.get("title") or it.get("name"))
        else:
            t = _s(it)
        if t:
            out.append(t)
    return out


def col(*kids, **o):
    d = {"box": "col", "children": [k for k in kids if k]}
    d.update(o)
    return d


def row(*kids, **o):
    d = {"box": "row", "children": [k for k in kids if k]}
    d.update(o)
    return d


def callout(page):
    tks = _texts(page.get("takeaways"))
    if not tks:
        return None
    return {"el": "callout", "text": "；".join(tks[:2])}


def _split_head(t):
    """「标题：说明」→ (标题, 说明)；短标题才拆"""
    for sep in ("：", ":"):
        if sep in t:
            a, b = t.split(sep, 1)
            if 1 < len(a) <= 12 and b.strip():
                return a.strip(), b.strip()
    return "", t


# ── 各页型 ─────────────────────────────────────────

def d_bullets(page):
    out = []
    groups = page.get("groups") or []
    if groups:
        gs = [g for g in groups if _texts(g.get("items")) or _s(g.get("heading"))]
        cards = [col({"el": "heading", "text": _s(g.get("heading")) or "要点", "role": "lead", "color": "primary"},
                     {"el": "bullets", "items": _texts(g.get("items")), "marker": "dot"},
                     style="topbar", gap="s") for g in gs]
        out.append(("groups-cards", col(row(*cards, gap="m"), callout(page))))
        bands = [row({"el": "heading", "text": _s(g.get("heading")) or "要点", "role": "lead", "color": "primary", "w": 3},
                     {"el": "bullets", "items": _texts(g.get("items")), "marker": "dot", "w": 9},
                     style="leftbar", gap="l") for g in gs]
        out.append(("groups-bands", col(*(bands + [callout(page)]), gap="m")))
        return out
    items = _texts(page.get("items"))
    if not items:
        return out
    split = [_split_head(t) for t in items]
    has_heads = sum(1 for h, _ in split if h) >= max(2, len(items) - 1)
    objs = [{"head": h, "text": t} for h, t in split] if has_heads else items
    out.append(("list", col({"el": "bullets", "items": objs, "marker": "num" if len(items) >= 3 else "dot", "role": "lead"},
                            callout(page))))
    if has_heads and 3 <= len(items) <= 6:
        rows_ = []
        for i, (h, t) in enumerate(split):
            if i:
                rows_.append({"el": "divider"})
            rows_.append(row({"el": "heading", "text": h, "role": "h2", "color": "primary", "w": 3},
                             {"el": "text", "text": t, "role": "lead", "w": 9}, gap="l"))
        out.append(("head-rows", col(*(rows_ + [callout(page)]), gap="m", align="spread")))
    if len(items) >= 4:
        half = (len(items) + 1) // 2
        a = objs[:half]
        b = objs[half:]
        out.append(("two-col", col(row({"el": "bullets", "items": a, "marker": "dot"},
                                       {"el": "bullets", "items": b, "marker": "dot"}, gap="l"), callout(page))))
    if 2 <= len(items) <= 4:
        cards = []
        for i, (h, t) in enumerate(split):
            cards.append({"el": "iconitem", "head": h or None, "text": t, "layout": "top", "style": "topbar"})
        out.append(("cards", col(row(*cards, gap="m"), callout(page))))
    if 4 <= len(items) <= 6:
        cards = [{"el": "iconitem", "head": h or None, "text": t, "layout": "left", "style": "soft"} for h, t in split]
        out.append(("grid", col({"box": "grid", "cols": 3 if len(items) in (5, 6) else 2, "children":
                                 [dict(c, layout="top") for c in cards] if len(items) in (5, 6) else cards, "gap": "m"},
                                callout(page))))
    if 3 <= len(items) <= 6:
        h0, t0 = split[0]
        lead = col({"el": "text", "text": "01", "role": "h2", "color": "white", "bold": True},
                   {"el": "heading", "text": h0 or t0, "role": "h1" if len(h0 or t0) <= 8 else "h2", "color": "white"},
                   {"el": "text", "text": t0, "role": "body", "color": "white"} if h0 else None,
                   style="accent", pad="l", gap="s", w=5)
        rest = [{"el": "step", "n": "%02d" % (i + 2), "head": h or None, "text": t, "layout": "left"}
                for i, (h, t) in enumerate(split[1:])]
        out.append(("lead-first", row(lead, col(*rest, gap="m", align="spread", w=7), gap="l")))
        steps = [{"el": "step", "n": "%02d" % (i + 1), "head": h or None, "text": t, "layout": "top", "style": "soft",
                  "pad": "l"} for i, (h, t) in enumerate(split)]
        out.append(("num-grid", col({"box": "grid", "cols": 3 if len(items) in (3, 5, 6) else 2, "children": steps,
                                     "gap": "m"}, callout(page))))
    tks = _texts(page.get("takeaways"))
    if tks and len(items) >= 3:
        out.append(("side-claim", row(col({"el": "heading", "kicker": "核心判断", "text": tks[0], "role": "h2",
                                             "color": "primary"}, style="soft", pad="l", w=4),
                                        {"el": "bullets", "items": objs, "marker": "bar", "w": 8}, gap="l")))
    return out


def d_stats(page):
    out = []
    st = [s for s in page.get("stats") or [] if _s(s.get("value"))]
    if not st:
        return out
    kpis = [{"el": "kpi", "value": _s(s.get("value")), "label": _s(s.get("label")), "delta": s.get("delta")} for s in st]
    out.append(("kpi-cards", col(row(*[dict(k, style="soft", pad="l") for k in kpis], gap="m"), callout(page))))
    out.append(("kpi-topbar", col(row(*[dict(k, style="topbar", pad="l") for k in kpis], gap="m"), callout(page))))
    tks = _texts(page.get("takeaways"))
    if len(kpis) == 4 or (len(tks) >= 2 and len(kpis) >= 2):
        g = {"box": "grid", "cols": 2, "children": [dict(k, style="leftbar") for k in kpis], "gap": "l", "w": 7}
        right = col({"el": "heading", "text": "解读", "role": "lead", "color": "primary"},
                    {"el": "bullets", "items": tks or [k["label"] for k in kpis], "marker": "check"},
                    style="soft", pad="l", gap="m", w=5) if len(tks) >= 2 else None
        out.append(("kpi-grid", row(g, right, gap="l") if right else g))
    out.append(("kpi-plain", col(row(*[dict(k, valign="top") for k in kpis], gap="l"), {"el": "divider"},
                                 callout(page), gap="l")))
    out += d_stats_extra(page, kpis)
    if 3 <= len(kpis) <= 4:
        hero = dict(kpis[0], style="accent", pad="l")
        rest = col(*[dict(k, style="leftbar") for k in kpis[1:]], gap="m", align="spread", w=6)
        out.append(("kpi-hero", col(row(dict(hero, w=6), rest, gap="l"), callout(page))))
    return out


def d_columns(page):
    out = []
    cols = [c for c in page.get("cols") or [] if _s(c.get("heading")) or _s(c.get("text"))]
    if not cols:
        return out
    items = [{"el": "iconitem", "icon": c.get("icon"), "head": _s(c.get("heading")) or None, "text": _s(c.get("text"))}
             for c in cols]
    out.append(("cards-top", col(row(*[dict(i, layout="top", style="topbar", pad="l") for i in items], gap="m"),
                                 callout(page))))
    out.append(("plain-top", col(row(*[dict(i, layout="top") for i in items], gap="l"), callout(page))))
    out.append(("bands", col(*([dict(i, layout="left", style="soft") for i in items] + [callout(page)]), gap="m")))
    nums = [{"el": "step", "n": "%02d" % (k + 1), "head": i["head"], "text": i["text"], "layout": "top", "style": "soft",
             "pad": "l"} for k, i in enumerate(items)]
    out.append(("num-grid", col(row(*nums, gap="m"), callout(page))))
    if len(items) == 4:
        out.append(("grid", col({"box": "grid", "cols": 2, "children": [dict(i, layout="left", style="outline") for i in items],
                                 "gap": "m"}, callout(page))))
    return out


def d_iconlist(page):
    out = []
    its = [i for i in page.get("iconItems") or [] if _s(i.get("heading")) or _s(i.get("desc"))]
    if not its:
        return out
    items = [{"el": "iconitem", "icon": i.get("icon"), "head": _s(i.get("heading")) or None, "text": _s(i.get("desc")),
              "layout": "left"} for i in its]
    out.append(("grid2", col({"box": "grid", "cols": 2, "children": items, "gap": "l"}, callout(page))))
    out.append(("grid2-soft", col({"box": "grid", "cols": 2, "children": [dict(i, style="soft") for i in items],
                                   "gap": "m"}, callout(page))))
    if len(items) <= 5:
        out.append(("list", col(*(items + [callout(page)]), gap="m", align="spread")))
    nums = [{"el": "step", "n": "%02d" % (k + 1), "head": i["head"], "text": i["text"], "layout": "left"}
            for k, i in enumerate(items)]
    out.append(("num-rows", col({"box": "grid", "cols": 2, "children": nums, "gap": "l"}, callout(page))))
    if len(items) in (3, 6):
        out.append(("grid3", col({"box": "grid", "cols": 3, "children": [dict(i, layout="top", style="topbar") for i in items],
                                  "gap": "m"}, callout(page))))
    return out


def d_compare(page):
    out = []
    L, R = page.get("left") or {}, page.get("right") or {}
    lp, rp = _texts(L.get("points")), _texts(R.get("points"))
    if not (lp or rp):
        return out

    def side(name, pts, style, marker):
        return col({"el": "heading", "text": _s(name) or "—", "role": "h2", "color": "ink" if style != "accent" else "white"},
                   {"el": "bullets", "items": pts, "marker": marker}, style=style, pad="l", gap="m")
    out.append(("soft-accent", col(row(side(L.get("name"), lp, "soft", "dot"), side(R.get("name"), rp, "accent", "check"),
                                       gap="m"), callout(page))))
    out.append(("outline", col(row(side(L.get("name"), lp, "outline", "dot"), side(R.get("name"), rp, "topbar", "check"),
                                   gap="l"), callout(page))))
    return out


def d_steps(page):
    out = []
    st = [s for s in page.get("steps") or [] if _s(s.get("title")) or _s(s.get("desc"))]
    if not st:
        return out
    items = [{"el": "step", "n": "%02d" % (i + 1), "head": _s(s.get("title")) or None, "text": _s(s.get("desc"))}
             for i, s in enumerate(st)]
    if len(items) <= 4:
        r = row(*[dict(i, layout="top", style="topbar", pad="l") for i in items], gap="m")
        r["seq"] = True
        out.append(("cards", col(r, callout(page))))
    out.append(("rows", col(*([dict(i, layout="left", style="leftbar") for i in items] + [callout(page)]), gap="m",
                            align="spread")))
    if len(items) in (5, 6):
        out.append(("grid3", col({"box": "grid", "cols": 3, "children": [dict(i, layout="top", style="soft") for i in items],
                                  "gap": "m"}, callout(page))))
    return out


def d_chart(page):
    out = []
    ch = page.get("chart")
    if not ch:
        return out
    tks = _texts(page.get("takeaways"))
    chart = {"el": "chart", "chart": ch}
    if tks:
        out.append(("chart-side", row(dict(chart, w=8),
                                      col({"el": "heading", "text": "要点", "role": "lead", "color": "primary"},
                                          {"el": "bullets", "items": tks, "marker": "num"}, style="soft", pad="l",
                                          gap="m", w=4), gap="l")))
        out.append(("chart-callout", col(chart, {"el": "callout", "text": "；".join(tks[:2])})))
    else:
        out.append(("chart-full", col(chart)))
    return out


def d_combo(page):
    out = []
    st = [s for s in page.get("stats") or [] if _s(s.get("value"))]
    ch = page.get("chart")
    if not (st and ch):
        return out
    kpis = [{"el": "kpi", "value": _s(s.get("value")), "label": _s(s.get("label")), "style": "leftbar"} for s in st[:4]]
    out.append(("kpis-chart", row(col(*kpis, gap="m", align="spread", w=4), {"el": "chart", "chart": ch, "w": 8}, gap="l")))
    out.append(("kpirow-chart", col(row(*[dict(k, style="soft", pad="m") for k in kpis], gap="m"),
                                    {"el": "chart", "chart": ch})))
    return out


def d_table(page):
    heads, rows = page.get("headers") or [], page.get("rows") or []
    if not rows:
        return []
    t = {"el": "table", "headers": heads, "rows": rows}
    tks = _texts(page.get("takeaways"))
    out = [("table", col(t, callout(page)))]
    if tks:
        out.append(("table-side", row(dict(t, w=8), col({"el": "heading", "text": "解读", "role": "lead", "color": "primary"},
                                                         {"el": "bullets", "items": tks, "marker": "check"},
                                                         style="soft", pad="l", gap="m", w=4), gap="l")))
    return out


def _pctv(v):
    try:
        t = str(v).strip()
        if not t.endswith("%"):
            return None
        return float(t[:-1].replace(",", ""))
    except ValueError:
        return None


def d_stats_extra(page, kpis):
    """全是百分数的指标：圆环 / 进度条"""
    out = []
    pcts = [_pctv(k["value"]) for k in kpis]
    if kpis and all(p is not None for p in pcts) and len(kpis) <= 4:
        rings = [{"el": "ring", "value": p, "display": k["value"], "label": k["label"]} for p, k in zip(pcts, kpis)]
        out.append(("rings", col(row(*rings, gap="l"), callout(page))))
        bars = [{"el": "progress", "value": p, "display": k["value"], "label": k["label"]} for p, k in zip(pcts, kpis)]
        out.append(("bars", col(*(bars + [callout(page)]), gap="l", align="spread")))
    return out


def d_timeline(page):
    tl = [t for t in page.get("timeline") or [] if _s(t.get("title")) or _s(t.get("label"))]
    if not tl:
        return []
    items = [{"el": "step", "n": _s(t.get("label")) or "%02d" % (i + 1), "head": _s(t.get("title")) or None,
              "text": _s(t.get("desc"))} for i, t in enumerate(tl)]
    out = []
    if len(items) <= 4:
        out.append(("tl-cards", col(row(*[dict(i, layout="top", style="topbar", pad="l") for i in items], gap="m"),
                                    callout(page))))
    out.append(("tl-rows", col(*([dict(i, layout="left", style="leftbar") for i in items] + [callout(page)]),
                               gap="m", align="spread")))
    if len(items) in (5, 6):
        out.append(("tl-grid", col({"box": "grid", "cols": 3, "children": [dict(i, layout="top", style="soft") for i in items],
                                    "gap": "m"}, callout(page))))
    return out


def d_matrix(page):
    qs = page.get("quadrants") or []
    if len(qs) < 4:
        return []
    styles = ["accent", "soft", "soft", "outline"]
    cards = [col({"el": "heading", "text": _s(q.get("name")) or "—", "role": "lead",
                  "color": "white" if st == "accent" else "primary"},
                 {"el": "bullets", "items": _texts(q.get("items")), "marker": "dot", "role": "lead"}, style=st, pad="l", gap="m")
             for q, st in zip(qs[:4], styles)]
    out = [("matrix-cards", col({"box": "grid", "cols": 2, "children": cards, "gap": "m"}))]
    plain = [col({"el": "heading", "text": _s(q.get("name")) or "—", "role": "lead", "color": "primary"},
                 {"el": "bullets", "items": _texts(q.get("items")), "marker": "check", "role": "lead"}, style="leftbar", gap="m")
             for q in qs[:4]]
    out.append(("matrix-lines", col({"box": "grid", "cols": 2, "children": plain, "gap": "l"})))
    return out


def d_quote(page):
    q = _s(page.get("quote"))
    if not q:
        return []
    by = _s(page.get("subtitle"))
    return [("quote-center", col({"el": "quote", "text": q, "by": by or None, "align": "center"}, align="center")),
            ("quote-card", row({"el": "quote", "text": q, "by": by or None, "style": "soft", "pad": "l", "w": 9},
                               {"el": "iconitem", "icon": None, "head": "核心判断", "text": by or "", "layout": "top", "w": 3}
                               if by else None, gap="l"))]


def d_kpi(page):
    gs = [g for g in page.get("gauges") or [] if g.get("label")]
    if not gs:
        return []
    def disp(g):
        return _s(g.get("display")) or ("%s%%" % g.get("value"))
    rings = [{"el": "ring", "value": g.get("value"), "display": disp(g), "label": _s(g.get("label"))} for g in gs[:4]]
    bars = [{"el": "progress", "value": g.get("value"), "display": disp(g), "label": _s(g.get("label")),
             "target": _s(g.get("target")) or None, "good_at": 100 if any(float(x.get("value") or 0) > 100 for x in gs) else 0}
            for g in gs[:6]]
    out = [("kpi-rings", col(row(*rings, gap="l"), callout(page))),
           ("kpi-bars", col(*(bars + [callout(page)]), gap="l", align="spread"))]
    return out


def d_imagetext(page):
    img = page.get("image")
    items = _texts(page.get("items"))
    if not img or not items:
        return []
    pic = {"el": "image", "src": img, "w": 6}
    lst = col({"el": "bullets", "items": items, "marker": "check", "role": "lead"}, callout(page), gap="l", w=6)
    left = (page.get("direction") or "left") != "right"
    return [("img-split", row(*((pic, lst) if left else (lst, pic)), gap="l")),
            ("img-top", col(dict(pic, w=None), row(*[{"el": "text", "text": t, "role": "body", "style": "leftbar"}
                                                    for t in items[:4]], gap="m")))]


def d_faq(page):
    fs = [f for f in page.get("faqs") or [] if _s(f.get("q"))]
    if not fs:
        return []
    qa = [col({"el": "heading", "text": "Q：" + _s(f.get("q")), "role": "h2", "color": "primary"},
              {"el": "text", "text": _s(f.get("a")), "role": "lead"}, gap="s") for f in fs]
    out = [("faq-list", col(*qa, gap="l", align="spread")),
           ("faq-bands", col(*[dict(q, style="leftbar") for q in qa], gap="l", align="spread"))]
    if len(qa) in (4, 6):
        out.append(("faq-grid", col({"box": "grid", "cols": 2, "children": [dict(q, style="soft", pad="l") for q in qa],
                                     "gap": "m"})))
    return out


# ════════════ 第三批构图 ════════════
def _clause(title, n=10):
    t = _s(title)
    for sep in ("，", ",", "：", ":", "；"):
        t = t.split(sep)[0]
    return t if 2 <= len(t) <= n else None


def _panel_claim(page, body):
    tks = _texts(page.get("takeaways"))
    if not tks:
        return None
    return ("panel-claim", row(col({"el": "text", "text": "核心判断", "role": "small", "color": "white", "bold": True},
                                   {"el": "heading", "text": tks[0], "role": "h2", "color": "white"},
                                   {"el": "text", "text": tks[1], "role": "body", "color": "white"} if len(tks) > 1 else None,
                                   style="panel", pad="l", gap="m", align="center", w=4), dict(body, w=8), gap="l"))


def _hub(page, items, center=None):
    c = center or _clause(page.get("title"))
    if not c or not 3 <= len(items) <= 6:
        return None
    return ("hub", col({"el": "hub", "center": c, "items": items}, callout(page)))


def extra_candidates(page):
    t = page.get("type")
    out = []
    if t == "bullets" and not page.get("groups"):
        items = _texts(page.get("items"))
        split = [_split_head(x) for x in items]
        objs = [{"head": h, "text": x} for h, x in split]
        pc = _panel_claim(page, {"el": "bullets", "items": objs, "marker": "num", "role": "lead"})
        if pc:
            out.append(pc)
        if sum(1 for h, _ in split if h) >= len(items) - 1:
            hb = _hub(page, objs)
            if hb:
                out.append(hb)
    elif t in ("columns", "iconlist"):
        src = page.get("cols") if t == "columns" else page.get("iconItems")
        items = [{"head": _s(c.get("heading")), "text": _s(c.get("text") or c.get("desc")), "icon": c.get("icon")}
                 for c in src or []]
        if 3 <= len(items) <= 5:
            out.append(("orbs", col({"el": "orbs", "items": items}, callout(page), gap="l")))
        hb = _hub(page, items)
        if hb:
            out.append(hb)
    elif t == "steps":
        st = [s_ for s_ in page.get("steps") or [] if _s(s_.get("title")) or _s(s_.get("desc"))]
        if 3 <= len(st) <= 5:
            out.append(("flow", col({"el": "flow", "items": [{"head": _s(s_.get("title")), "text": _s(s_.get("desc"))}
                                                            for s_ in st]}, callout(page), gap="l")))
            out.append(("orbs", col({"el": "orbs", "items": [{"head": _s(s_.get("title")), "text": _s(s_.get("desc")),
                                                             "icon": s_.get("icon")} for s_ in st]}, callout(page), gap="l")))
            out.append(("tl-line", col({"el": "timeline", "items": [{"label": "%02d" % (i + 1), "head": _s(s_.get("title")),
                                                                     "text": _s(s_.get("desc"))} for i, s_ in enumerate(st)]},
                                       callout(page), gap="l")))
    elif t == "timeline":
        tl = [x for x in page.get("timeline") or [] if _s(x.get("title")) or _s(x.get("label"))]
        if 3 <= len(tl) <= 6:
            out.append(("tl-line", col({"el": "timeline", "items": [{"label": _s(x.get("label")), "head": _s(x.get("title")),
                                                                     "text": _s(x.get("desc"))} for x in tl]},
                                       callout(page), gap="l")))
            if len(tl) <= 5:
                out.append(("flow", col({"el": "flow", "items": [{"head": _s(x.get("label")), "text": "%s：%s" % (
                    _s(x.get("title")), _s(x.get("desc"))) if _s(x.get("desc")) else _s(x.get("title"))} for x in tl]},
                    callout(page), gap="l")))
    elif t == "table":
        heads, rows = page.get("headers") or [], page.get("rows") or []
        ncol = max((len(r) for r in rows), default=0)
        for ci in range(1, ncol):
            vals = [r[ci] if ci < len(r) else "" for r in rows]
            nums = []
            for v in vals:
                try:
                    nums.append(float(str(v).replace(",", "").replace("%", "")))
                except ValueError:
                    nums = None
                    break
            if nums and 3 <= len(rows) <= 8:
                title = _s(heads[ci]) if ci < len(heads) else ""
                bars = {"el": "hbars", "items": [{"label": _s(r[0]), "value": v, "display": _s(r[ci])}
                                                 for r, v in zip(rows, nums)]}
                tks = _texts(page.get("takeaways"))
                side = col({"el": "heading", "text": "解读", "role": "lead", "color": "primary"},
                           {"el": "bullets", "items": tks, "marker": "check"}, style="soft", pad="l", gap="m", w=4) if tks else None
                out.append(("table-bars", row(col({"el": "heading", "text": title, "role": "lead"} if title else None,
                                                  bars, gap="m", w=8), side, gap="l")))
                break
    elif t == "compare":
        L, R = page.get("left") or {}, page.get("right") or {}
        lp, rp = _texts(L.get("points")), _texts(R.get("points"))
        if lp and rp:
            def side(name, pts, style, marker):
                return col({"el": "heading", "text": _s(name) or "—", "role": "h2", "color": "white" if style == "accent" else "ink"},
                           {"el": "bullets", "items": pts, "marker": marker, "role": "lead"}, style=style, pad="l", gap="m", w=5)
            out.append(("versus", col(row(side(L.get("name"), lp, "soft", "dot"), {"el": "badge", "text": "VS", "w": 1.2},
                                          side(R.get("name"), rp, "accent", "check"), gap="s"), callout(page))))
    elif t == "chart" and page.get("chart"):
        tks = _texts(page.get("takeaways"))
        if tks:
            out.append(("chart-panel", row(col({"el": "text", "text": "要点", "role": "lead", "color": "white", "bold": True},
                                               {"el": "bullets", "items": tks, "marker": "num"}, style="panel", pad="l",
                                               gap="m", align="center", w=4),
                                           {"el": "chart", "chart": page["chart"], "w": 8}, gap="l")))
    elif t == "quote" and _s(page.get("quote")):
        out.append(("quote-panel", col({"el": "quote", "text": _s(page.get("quote")), "by": _s(page.get("subtitle")) or None},
                                       style="panel", pad="l", align="center")))
    elif t == "stats":
        st = [x for x in page.get("stats") or [] if _s(x.get("value"))]
        if 3 <= len(st) <= 4:
            kp = [{"el": "kpi", "value": _s(x.get("value")), "label": _s(x.get("label"))} for x in st]
            out.append(("kpi-panel", row(dict(kp[0], style="panel", pad="l", w=5),
                                         col(*[dict(k, style="leftbar") for k in kp[1:]] + [callout(page)], gap="m",
                                             align="spread", w=7), gap="l")))
    elif t == "matrix":
        qs = page.get("quadrants") or []
        if len(qs) >= 4 and (page.get("xLabel") or page.get("yLabel")):
            cards = [col({"el": "heading", "text": _s(q.get("name")) or "—", "role": "lead", "color": "primary"},
                         {"el": "bullets", "items": _texts(q.get("items")), "marker": "dot", "role": "lead"},
                         style="outline", pad="l", gap="s") for q in qs[:4]]
            out.append(("matrix-axes", col({"el": "text", "text": _s(page.get("yLabel")), "role": "small", "color": "muted",
                                            "bold": True} if page.get("yLabel") else None,
                                           {"box": "grid", "cols": 2, "children": cards, "gap": "s"},
                                           {"el": "text", "text": _s(page.get("xLabel")), "role": "small", "color": "muted",
                                            "bold": True, "align": "right"} if page.get("xLabel") else None, gap="s")))
    return [o for o in out if o]


DESIGNERS = {"bullets": d_bullets, "stats": d_stats, "columns": d_columns, "iconlist": d_iconlist,
             "compare": d_compare, "steps": d_steps, "chart": d_chart, "combo": d_combo, "table": d_table,
             "timeline": d_timeline, "matrix": d_matrix, "quote": d_quote, "kpi": d_kpi, "imagetext": d_imagetext,
             "faq": d_faq}


def candidates(page):
    fn = DESIGNERS.get(page.get("type"))
    if not fn:
        return []
    # 带高亮/注释的单系列图表：底层引擎 的「注释图」版式更好，交给它
    if page.get("type") == "chart" and (page.get("chart") or {}).get("annotation"):
        return []
    return fn(page) + extra_candidates(page)


def flatten_to_page(tree, title):
    """AI 版面彻底不合格时：把里面的文字收集成一个要点页，交给程序重新设计"""
    texts = []

    def walk(n):
        if not isinstance(n, dict):
            return
        if "el" in n or "text" in n or "items" in n:
            for k in ("text", "head", "label"):
                if _s(n.get(k)) and k != "label":
                    pass
            if _s(n.get("value")):
                texts.append(("%s %s" % (_s(n.get("value")), _s(n.get("label")))).strip())
            elif _s(n.get("head")) and _s(n.get("text")):
                texts.append("%s：%s" % (_s(n["head"]), _s(n["text"])))
            elif _s(n.get("text")) and n.get("el") not in ("heading",):
                texts.append(_s(n["text"]))
            for it in n.get("items") or []:
                if isinstance(it, dict):
                    h, t = _s(it.get("head")), _s(it.get("text"))
                    texts.append("%s：%s" % (h, t) if h and t else (h or t))
                elif _s(it):
                    texts.append(_s(it))
        for c in n.get("children") or []:
            walk(c)
    walk(tree)
    return {"type": "bullets", "title": title, "items": [{"text": t} for t in texts[:8] if t]}
