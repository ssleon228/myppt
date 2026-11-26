"""版面元素（积木的叶子）：每种元素都会「量高度」和「画出来」。

量高度 measure(node, w, L) → 在宽 w、字号档位 L 下需要的高度（px）。
画 draw(ctx, node, box, L, tone)：box = (x, y, w, h)，tone = "light"|"dark"（深色卡片里文字反白）。
弹性元素（图表、图片、留白）没有固有高度：只有最小高度，剩余空间优先给它们。
"""
import re

from .engine.ooxml.util import mix

from . import measure as M
from .tokens import size, LINE_H, LEVELS


def P(px):
    return px / 2.0


def IN(px):
    return px / 144.0


FLEX = {"chart": 340, "image": 280, "spacer": 0}  # 弹性元素 → 最小高度


def _s(v):
    return "" if v is None else str(v).strip()


def _items(n):
    out = []
    for it in n.get("items") or []:
        if isinstance(it, dict):
            head, text = _s(it.get("head") or it.get("heading") or it.get("title")), _s(it.get("text") or it.get("desc"))
            if head or text:
                out.append({"head": head, "text": text, "icon": it.get("icon")})
        elif _s(it):
            out.append({"head": "", "text": _s(it), "icon": None})
    return out


# ── 颜色 ─────────────────────────────────────────────

def color(ctx, role, tone):
    p = ctx.pal
    if tone == "dark":
        return {"ink": "FFFFFF", "white": "FFFFFF", "primary": "FFFFFF", "accent": "FFFFFF",
                "muted": mix("FFFFFF", ctx.dark_bg or p["dark"], 0.28), "good": "FFFFFF", "warn": "FFFFFF",
                "dark": "FFFFFF"}.get(role, "FFFFFF")
    return p.get(role) or p["ink"]


# ── 文字画法 ─────────────────────────────────────────

# 数字高亮：正文里的数据（带单位）自动加粗上主色 —— 读者一眼扫到关键数
_HL = re.compile(r"([+\-−]?\d[\d,.]*\s*(?:%|‰|个百分点|百分点|亿元|万元|千元|亿|万户|万笔|万|千|元|笔|户|家|个|项|天|分钟|小时|倍|bp|BP|pp)?)")


def hl_runs(text, col, hcol):
    """→ runs；没有数字返回 None。年份（4 位整数 + 年）和序号不高亮"""
    t = _s(text)
    parts = _HL.split(t)
    if len(parts) < 3:
        return None
    runs, hit = [], 0
    for i, seg in enumerate(parts):
        if not seg:
            continue
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        is_num = i % 2 == 1
        if is_num and (re.match(r"^\d{4}$", seg.strip()) and nxt.startswith(("年", "-", "Q"))):
            is_num = False  # 2026 年
        if is_num and re.match(r"^\d{1,2}$", seg.strip()) and nxt.startswith(("月", "日", "号", "季")):
            is_num = False  # 10 月
        prev = parts[i - 1] if i else ""
        if is_num and (re.match(r"^[A-Za-z]", nxt) or re.search(r"[A-Za-z]$", prev)):
            is_num = False  # 4S 店、Q3、A/B
        if is_num:
            hit += 1
            runs.append({"text": seg, "options": {"bold": True, "color": hcol}})
        else:
            runs.append({"text": seg, "options": {"color": col}})
    return runs if hit else None


def hl_color(ctx, tone):
    from . import styles as STY
    if tone != "light" or not STY.CUR.get("hl", True):
        return None
    return ctx.pal.get("primary")


def put_text(ctx, text, x, y, w, h, px, col, bold=False, align="left", valign="top", lh=1.3, runs=None, font=None,
             spacing=None, hl=None):
    if hl and runs is None and not bold:
        runs = hl_runs(text, col, hl)
    o = dict(x=IN(x), y=IN(y), w=IN(w), h=IN(max(h, px * 1.2)), fontSize=P(px), color=col, bold=bool(bold),
             fontFace=font or ctx.font, align=align, valign=valign, margin=0, lineSpacingMultiple=lh)
    if spacing:
        o["charSpacing"] = spacing
    ctx.slide.add_text(runs if runs is not None else text, **o)


# ── 数值拆分：数字大、单位小 ─────────────────────────────
_VAL = re.compile(r"^([^0-9+\-−.]*)([+\-−]?[0-9][0-9,.]*%?)(.*)$", re.S)
UNIT_K = 0.42


def split_value(v):
    m = _VAL.match(_s(v))
    if not m:
        return "", _s(v), ""
    return m.group(1), m.group(2), m.group(3)


def value_em(v):
    pre, num, post = split_value(v)
    return M.text_w(num, 1, True) + (M.text_w(pre + post, 1, True) * UNIT_K)


def value_px(v, w, L):
    em = max(0.5, value_em(v))
    return max(40, min(size("display", L), int((w * 0.94) / em / 2) * 2))


# ════════════════════════════════════════════════════
# 各元素
# ════════════════════════════════════════════════════

def m_heading(n, w, L):
    role = n.get("role") if n.get("role") in ("h1", "h2", "lead") else "h2"
    h = M.text_h(n["text"], w, size(role, L), LINE_H[role], True)
    if _s(n.get("kicker")):
        h += size("small", L) * 1.3 + 8
    if _s(n.get("sub")):
        h += 12 + M.text_h(n["sub"], w, size("body", L), 1.35)
    return h


def d_heading(ctx, n, box, L, tone):
    x, y, w, h = box
    role = n.get("role") if n.get("role") in ("h1", "h2", "lead") else "h2"
    al = n.get("align") or "left"
    if _s(n.get("kicker")):
        sp = size("small", L)
        put_text(ctx, n["kicker"], x, y, w, sp * 1.3, sp, color(ctx, "primary" if tone == "light" else "muted", tone),
                 bold=True, align=al, lh=1.0, spacing=2)
        y += sp * 1.3 + 8
    px = size(role, L)
    th = M.text_h(n["text"], w, px, LINE_H[role], True)
    put_text(ctx, n["text"], x, y, w, th, px, color(ctx, n.get("color") or "ink", tone), bold=True, align=al,
             lh=LINE_H[role])
    y += th
    if _s(n.get("sub")):
        bp = size("body", L)
        sh = M.text_h(n["sub"], w, bp, 1.35)
        put_text(ctx, n["sub"], x, y + 12, w, sh, bp, color(ctx, "muted", tone), align=al, lh=1.35)


def m_text(n, w, L):
    role = n.get("role") if n.get("role") in ("h2", "lead", "body", "small") else "body"
    return M.text_h(n["text"], w, size(role, L), LINE_H[role], bool(n.get("bold")))


def d_text(ctx, n, box, L, tone):
    x, y, w, h = box
    role = n.get("role") if n.get("role") in ("h2", "lead", "body", "small") else "body"
    px = size(role, L)
    put_text(ctx, n["text"], x, y, w, h, px, color(ctx, n.get("color") or "ink", tone), bold=bool(n.get("bold")),
             align=n.get("align") or "left", valign=n.get("valign") or "top", lh=LINE_H[role],
             hl=hl_color(ctx, tone) if role in ("body", "small") else None)


# ── 要点列表 ──
def _marker_w(marker, px):
    return {"dot": px * 1.0, "num": px * 1.7, "check": px * 1.3, "icon": px * 1.9, "bar": 26, "none": 0,
            "dash": px * 1.2, "square": px * 1.0, "diamond": px * 1.1, "ring": px * 1.1}.get(marker, px)


def _item_str(it):
    if it["head"] and it["text"]:
        return it["head"] + "　" + it["text"]
    return it["head"] or it["text"]


def _bullet_metrics(n, w, L):
    role = n.get("role") if n.get("role") in ("lead", "body", "small") else "body"
    px = size(role, L)
    marker = n.get("marker") or "dot"
    tw = w - _marker_w(marker, px)
    hs = [M.text_h(_item_str(it), tw, px, LINE_H[role], bool(it["head"])) for it in _items(n)]
    return role, px, marker, tw, hs


def m_bullets(n, w, L):
    role, px, marker, tw, hs = _bullet_metrics(n, w, L)
    if not hs:
        return 0
    return sum(hs) + px * 0.7 * (len(hs) - 1)


def d_bullets(ctx, n, box, L, tone):
    x, y, w, h = box
    role, px, marker, tw, hs = _bullet_metrics(n, w, L)
    items = _items(n)
    if not items:
        return
    gap = px * 0.7
    nat = sum(hs) + gap * (len(hs) - 1)
    if n.get("spread", True) and len(hs) > 1 and h > nat:
        gap = min(gap + (h - nat) / (len(hs) - 1), px * 2.2)
    mw = _marker_w(marker, px)
    lh = LINE_H[role]
    acc = color(ctx, "primary", tone)
    cy = y
    for i, (it, ih) in enumerate(zip(items, hs)):
        line1 = px * 1.2 * lh  # 首行高度：标记与首行垂直居中
        if marker == "dot":
            r = px * 0.16
            ctx.slide.add_shape("ellipse", x=IN(x + px * 0.12), y=IN(cy + line1 / 2 - r), w=IN(r * 2), h=IN(r * 2),
                                fill={"color": acc}, line={"type": "none"})
        elif marker == "dash":
            ctx.slide.add_shape("rect", x=IN(x), y=IN(cy + line1 / 2 - 2), w=IN(px * 0.6), h=IN(4),
                                fill={"color": acc}, line={"type": "none"})
        elif marker == "square":
            r = px * 0.17
            ctx.slide.add_shape("rect", x=IN(x + px * 0.1), y=IN(cy + line1 / 2 - r), w=IN(r * 2), h=IN(r * 2),
                                fill={"color": acc}, line={"type": "none"})
        elif marker == "diamond":
            r = px * 0.2
            ctx.slide.add_shape("diamond", x=IN(x + px * 0.1), y=IN(cy + line1 / 2 - r), w=IN(r * 2), h=IN(r * 2),
                                fill={"color": ctx.pal.get("accent_text", acc) if tone == "light" else acc},
                                line={"type": "none"})
        elif marker == "ring":
            r = px * 0.2
            ctx.slide.add_shape("ellipse", x=IN(x + px * 0.08), y=IN(cy + line1 / 2 - r), w=IN(r * 2), h=IN(r * 2),
                                fill={"type": "none"}, line={"color": acc, "width": 2})
        elif marker == "num":
            put_text(ctx, "%02d" % (i + 1), x, cy, mw, line1, px, acc, bold=True, valign="middle", lh=1.0,
                     font=ctx.latin or ctx.font)
        elif marker == "check":
            ctx.icon("fa-circle-check", None, x, cy + line1 / 2 - px * 0.48, px * 0.96, acc, "glyph")
        elif marker == "icon":
            ctx.icon(it.get("icon"), _item_str(it), x, cy + line1 / 2 - px * 0.75, px * 1.5, acc, "soft")
        elif marker == "bar":
            ctx.slide.add_shape("rect", x=IN(x), y=IN(cy + 4), w=IN(6), h=IN(max(ih - 8, px)),
                                fill={"color": acc}, line={"type": "none"})
        if it["head"] and it["text"]:
            runs = [{"text": it["head"] + "　", "options": {"bold": True, "color": color(ctx, "primary" if tone == "light" else "ink", tone)}},
                    ] + ((hl_runs(it["text"], color(ctx, "ink", tone), hl_color(ctx, tone)) if hl_color(ctx, tone) else None)
                         or [{"text": it["text"], "options": {"color": color(ctx, "ink", tone)}}])
            put_text(ctx, None, x + mw, cy, tw, ih, px, color(ctx, "ink", tone), lh=lh, runs=runs)
        else:
            put_text(ctx, _item_str(it), x + mw, cy, tw, ih, px, color(ctx, "ink", tone), bold=bool(it["head"]), lh=lh,
                     hl=hl_color(ctx, tone))
        cy += ih + gap


# ── 大数字 ──
def m_kpi(n, w, L):
    vp = value_px(n["value"], w, L)
    h = vp * 1.15
    if _s(n.get("label")):
        h += 10 + M.text_h(n["label"], w, size("body", L), 1.3)
    if _s(n.get("delta")):
        h += 8 + size("small", L) * 1.3
    if n.get("icon"):
        h += _icon_px(L) * 0.8 + 16
    return h


def _icon_px(L):
    return max(52, min(92, int(64 * LEVELS[L])))


def d_kpi(ctx, n, box, L, tone):
    x, y, w, h = box
    nat = m_kpi(n, w, L)
    if n.get("valign", "middle") == "middle" and h > nat:
        y += (h - nat) / 2
    al = n.get("align") or "left"
    if n.get("icon"):
        ip = _icon_px(L) * 0.8
        ix = x if al == "left" else x + (w - ip) / 2
        ctx.icon(n.get("icon"), n.get("label"), ix, y, ip, color(ctx, "primary", tone), "glyph")
        y += ip + 16
    vp = value_px(n["value"], w, L)
    pre, num, post = split_value(n["value"])
    from .styles import CUR
    kc = CUR.get("kpi") or "primary"
    if kc == "accent" and tone == "light":
        vc = ctx.pal.get("accent_text") or ctx.pal["primary"]
    else:
        vc = color(ctx, n.get("color") or (kc if kc in ("ink", "primary") else "primary"), tone)
    up = max(20, int(vp * UNIT_K))
    runs = []
    if pre:
        runs.append({"text": pre, "options": {"fontSize": P(up), "bold": True, "color": vc}})
    runs.append({"text": num, "options": {"fontSize": P(vp), "bold": True, "color": vc, "fontFace": ctx.latin or ctx.font}})
    if post:
        runs.append({"text": post, "options": {"fontSize": P(up), "bold": True, "color": vc}})
    put_text(ctx, None, x, y, w, vp * 1.15, vp, vc, bold=True, align=al, valign="bottom", lh=1.0, runs=runs)
    y += vp * 1.15
    if _s(n.get("label")):
        bp = size("body", L)
        lh_ = M.text_h(n["label"], w, bp, 1.3)
        put_text(ctx, n["label"], x, y + 10, w, lh_, bp, color(ctx, "ink", tone), align=al, lh=1.3)
        y += 10 + lh_
    if _s(n.get("delta")):
        sp = size("small", L)
        d = _s(n["delta"])
        neg = d.startswith(("-", "−", "↓", "下降", "减少"))
        put_text(ctx, d, x, y + 8, w, sp * 1.3, sp, color(ctx, "warn" if neg else "good", tone), bold=True, align=al,
                 lh=1.0)


# ── 图标条目 ──
def _ii(n, w, L):
    ip = _icon_px(L)
    hp, bp = size("lead", L), size("body", L)
    lay = n.get("layout") or "top"
    tw = w if lay == "top" else w - ip - 24
    hh = M.text_h(n.get("head"), tw, hp, 1.25, True) if _s(n.get("head")) else 0
    th = M.text_h(n.get("text"), tw, bp, 1.35) if _s(n.get("text")) else 0
    return ip, hp, bp, lay, tw, hh, th


def m_iconitem(n, w, L):
    ip, hp, bp, lay, tw, hh, th = _ii(n, w, L)
    body = hh + (10 if hh and th else 0) + th
    if lay == "top":
        return ip + 24 + body
    return max(ip, body)


def d_iconitem(ctx, n, box, L, tone):
    x, y, w, h = box
    ip, hp, bp, lay, tw, hh, th = _ii(n, w, L)
    acc = color(ctx, "primary", tone)
    style = "solid" if tone == "light" else "glyph"
    if lay == "top":
        ctx.icon(n.get("icon"), (n.get("head") or "") + (n.get("text") or ""), x, y, ip, acc, style)
        ty, tx = y + ip + 24, x
    else:
        ctx.icon(n.get("icon"), (n.get("head") or "") + (n.get("text") or ""), x, y, ip, acc, style)
        ty, tx = y + max(0, (ip - hh - th - 10) / 2) if hh + th < ip else y, x + ip + 24
    if hh:
        put_text(ctx, n["head"], tx, ty, tw, hh, hp, color(ctx, "ink", tone), bold=True, lh=1.25)
        ty += hh + 10
    if th:
        put_text(ctx, n["text"], tx, ty, tw, th, bp, color(ctx, "muted" if tone == "light" else "ink", tone), lh=1.35,
                 hl=hl_color(ctx, tone))


# ── 步骤 ──
def _st(n, w, L):
    np_ = size("h1", L)
    hp, bp = size("lead", L), size("body", L)
    lay = n.get("layout") or "top"
    tw = w if lay == "top" else w - np_ * 1.9
    hh = M.text_h(n.get("head"), tw, hp, 1.25, True) if _s(n.get("head")) else 0
    th = M.text_h(n.get("text"), tw, bp, 1.35) if _s(n.get("text")) else 0
    return np_, hp, bp, lay, tw, hh, th


def m_step(n, w, L):
    np_, hp, bp, lay, tw, hh, th = _st(n, w, L)
    body = hh + (10 if hh and th else 0) + th
    if lay == "top":
        return np_ * 1.1 + 16 + body
    return max(np_ * 1.1, body)


def d_step(ctx, n, box, L, tone):
    x, y, w, h = box
    np_, hp, bp, lay, tw, hh, th = _st(n, w, L)
    num = _s(n.get("n")) or "01"
    acc = color(ctx, "primary", tone)
    put_text(ctx, num, x, y, np_ * 2.2, np_ * 1.1, np_, acc, bold=True, lh=1.0, valign="top", font=ctx.latin or ctx.font)
    if lay == "top":
        ty, tx = y + np_ * 1.1 + 16, x
    else:
        ty, tx = y + 4, x + np_ * 1.9
    if hh:
        put_text(ctx, n["head"], tx, ty, tw, hh, hp, color(ctx, "ink", tone), bold=True, lh=1.25)
        ty += hh + 10
    if th:
        put_text(ctx, n["text"], tx, ty, tw, th, bp, color(ctx, "muted" if tone == "light" else "ink", tone), lh=1.35,
                 hl=hl_color(ctx, tone))


# ── 金句 ──
def m_quote(n, w, L):
    qp = size("h2", L) + 6
    h = size("display", L) * 0.55 + M.text_h(n["text"], w, qp, 1.35, True)
    if _s(n.get("by")):
        h += 20 + size("body", L) * 1.3
    return h


def d_quote(ctx, n, box, L, tone):
    x, y, w, h = box
    nat = m_quote(n, w, L)
    if h > nat:
        y += (h - nat) / 2
    dp = size("display", L)
    al = n.get("align") or "left"
    put_text(ctx, "“", x, y - dp * 0.2, w, dp * 0.8, dp, color(ctx, "primary", tone), bold=True, align=al, lh=1.0,
             font=ctx.latin or ctx.font)
    y += dp * 0.55
    qp = size("h2", L) + 6
    th = M.text_h(n["text"], w, qp, 1.35, True)
    put_text(ctx, n["text"], x, y, w, th, qp, color(ctx, "ink", tone), bold=True, align=al, lh=1.35)
    if _s(n.get("by")):
        bp = size("body", L)
        put_text(ctx, "—— " + n["by"], x, y + th + 20, w, bp * 1.3, bp, color(ctx, "muted", tone), align=al, lh=1.0)


# ── 结论条 ──
def _co(n, w, L):
    px = size("lead", L)
    pad_x, pad_y = 32, max(18, px * 0.6)
    ic = px * 1.3 if n.get("icon", True) else 0
    tw = w - pad_x * 2 - (ic + 20 if ic else 0)
    return px, pad_x, pad_y, ic, tw


def m_callout(n, w, L):
    px, pad_x, pad_y, ic, tw = _co(n, w, L)
    return M.text_h(n["text"], tw, px, 1.3, True) + pad_y * 2


def d_callout(ctx, n, box, L, tone):
    from .styles import CUR
    x, y, w, h = box
    px, pad_x, pad_y, ic, tw = _co(n, w, L)
    th = M.text_h(n["text"], tw, px, 1.3, True)
    kind = CUR.get("callout") or "bar"
    P_ = ctx.pal
    fg = "FFFFFF"
    icol = None
    if tone != "light":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": "FFFFFF"}, line={"type": "none"})
        fg = P_["primary"]
    elif kind == "pill":
        ctx.slide.add_shape("roundRect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), rectRadius=IN(h / 2),
                            fill={"color": P_["primary"]}, line={"type": "none"})
    elif kind == "quote":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(8), h=IN(h), fill={"color": P_.get("accent", P_["primary"])},
                            line={"type": "none"})
        fg = P_["ink"]
        icol = P_.get("accent_text") or P_["primary"]
    elif kind == "dark":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": P_["dark"]}, line={"type": "none"})
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w * 0.18), h=IN(8), fill={"color": P_.get("accent", P_["primary"])},
                            line={"type": "none"})
    elif kind == "fine":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"type": "none"},
                            line={"color": P_.get("accent", P_["primary"]), "width": 1})
        fg = P_["ink"]
        icol = P_.get("accent_text") or P_["primary"]
    elif kind == "code":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": P_["dark"]}, line={"type": "none"})
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(10), h=IN(h), fill={"color": P_.get("accent", P_["primary"])},
                            line={"type": "none"})
        icol = P_.get("accent", "FFFFFF")
    else:
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": P_["primary"]}, line={"type": "none"})
    ty = y + (h - th) / 2
    tx = x + pad_x
    if ic:
        ctx.icon(n.get("icon") if isinstance(n.get("icon"), str) else "fa-lightbulb", None, tx, y + (h - ic) / 2, ic,
                 icol or fg, "glyph")
        tx += ic + 20
    put_text(ctx, n["text"], tx, ty, tw, th, px, fg, bold=True, lh=1.3,
             align="center" if kind == "fine" and not ic else "left")


# ── 表格 ──
def _tb(n, w, L):
    px = size("body", L) - 2
    rh = px * 2.1
    return px, rh


def m_table(n, w, L):
    px, rh = _tb(n, w, L)
    rows = n.get("rows") or []
    extra = 0
    ncol = max(len(n.get("headers") or []), max((len(r) for r in rows), default=1))
    cw = w / max(1, ncol)
    for r in rows:
        mx = max((M.lines(str(c), cw - 24, px) for c in r), default=1)
        extra += (mx - 1) * px * 1.25
    return rh * (len(rows) + (1 if n.get("headers") else 0)) + extra


def d_table(ctx, n, box, L, tone):
    x, y, w, h = box
    px, rh = _tb(n, w, L)
    heads = [str(v) for v in n.get("headers") or []]
    rows = [[str(c) for c in r] for r in n.get("rows") or []]
    ncol = max(len(heads), max((len(r) for r in rows), default=1))
    nrow = len(rows) + (1 if heads else 0)
    nat = m_table(n, w, L)
    rh_scale = max(1.0, min(1.9, h / nat)) if nat else 1
    cw = w / ncol
    hl = n.get("highlight")
    data = []
    if heads:
        data.append([{"text": t, "options": {"bold": True, "color": "FFFFFF", "fill": {"color": ctx.pal["primary"]},
                                             "align": "left" if i == 0 else "center"}} for i, t in enumerate(heads + [""] * (ncol - len(heads)))])
    for ri, r in enumerate(rows):
        fill = ctx.pal["soft"] if (ri == hl) else ("FFFFFF" if ri % 2 == 0 else ctx.pal["soft2"])
        data.append([{"text": c, "options": {"color": ctx.pal["ink"], "fill": {"color": fill}, "bold": ri == hl,
                                             "align": "left" if i == 0 else "center"}} for i, c in enumerate(r + [""] * (ncol - len(r)))])
    rhs = []
    for ri in range(nrow):
        rhs.append(IN(rh * rh_scale))
    ctx.slide.add_table(data, x=IN(x), y=IN(y), w=IN(w), colW=[IN(cw)] * ncol, rowH=rhs, fontSize=P(px),
                        fontFace=ctx.font, valign="middle", margin=[8, 10, 8, 10],
                        border=[{"type": "solid", "color": ctx.pal["line"], "pt": 0.75}, {"type": "none"},
                                {"type": "solid", "color": ctx.pal["line"], "pt": 0.75}, {"type": "none"}])


# ── 弹性元素 ──
def d_chart(ctx, n, box, L, tone):
    x, y, w, h = box
    from .engine.render import ad
    ctx.add_chart(ctx.slide, ad(dict(n["chart"])), ad(dict(x=x, y=y, w=w, h=h)))


def d_image(ctx, n, box, L, tone):
    x, y, w, h = box
    f = ctx.resolve_image(n.get("src"))
    if f:
        ctx.slide.add_image(path=f, x=IN(x), y=IN(y), w=IN(w), h=IN(h), sizing={"type": n.get("fit") or "cover"})
    else:
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": ctx.pal["soft2"]},
                            line={"type": "none"})
        put_text(ctx, "图片：" + _s(n.get("src")), x, y, w, h, 24, ctx.pal["muted"], align="center", valign="middle")
        ctx.warn("图片找不到：%s" % _s(n.get("src")))


def d_divider(ctx, n, box, L, tone):
    x, y, w, h = box
    ctx.slide.add_shape("line", x=IN(x), y=IN(y + h / 2), w=IN(w), h=0,
                        line={"color": color(ctx, "muted", tone) if tone == "dark" else ctx.pal["line"], "width": 1})


def _none(*a):
    return None


MEASURE = {
    "heading": m_heading, "text": m_text, "bullets": m_bullets, "kpi": m_kpi, "iconitem": m_iconitem,
    "step": m_step, "quote": m_quote, "callout": m_callout, "table": m_table,
    "chart": lambda n, w, L: FLEX["chart"], "image": lambda n, w, L: FLEX["image"],
    "spacer": lambda n, w, L: 0, "divider": lambda n, w, L: 4,
}
DRAW = {
    "heading": d_heading, "text": d_text, "bullets": d_bullets, "kpi": d_kpi, "iconitem": d_iconitem,
    "step": d_step, "quote": d_quote, "callout": d_callout, "table": d_table, "chart": d_chart, "image": d_image,
    "spacer": _none, "divider": d_divider,
}
LEAVES = tuple(MEASURE)


# ── 宽度利用率：文字实际占了框宽的多少（短字放在宽框里不算填满） ──
def use_ratio(n, w, L):
    el = n["el"]
    try:
        if el in ("text", "heading"):
            role = n.get("role") or ("h2" if el == "heading" else "body")
            role = role if role in ("h1", "h2", "lead", "body", "small") else "body"
            return min(1.0, M.widest(n["text"], w, size(role, L), True) / max(1.0, w))
        if el == "bullets":
            role, px, marker, tw, hs = _bullet_metrics(n, w, L)
            its = _items(n)
            if not its:
                return 1.0
            mw = _marker_w(marker, px)
            r = [min(1.0, (mw + M.widest(_item_str(it), tw, px)) / max(1.0, w)) for it in its]
            return sum(r) / len(r)
        if el == "kpi":
            vp = value_px(n["value"], w, L)
            a = value_em(n["value"]) * vp
            b = M.widest(n.get("label") or "", w, size("body", L))
            return min(1.0, max(a, b) / max(1.0, w))
    except Exception:  # noqa: BLE001
        return 1.0
    return 1.0


# ════════════ 新增元素：进度条、圆环 ════════════
def _pct(n):
    try:
        return float(str(n.get("value")).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _disp(n):
    v = _s(n.get("display"))
    if v:
        return v
    p = _pct(n)
    return ("%g%%" % p) if p is not None else _s(n.get("value"))


def m_progress(n, w, L):
    bp = size("body", L)
    h = bp * 1.3 + 12 + max(12, int(14 * LEVELS[L]))
    if _s(n.get("target")):
        h += 8 + size("small", L) * 1.3
    return h


def d_progress(ctx, n, box, L, tone):
    x, y, w, h = box
    nat = m_progress(n, w, L)
    if h > nat:
        y += (h - nat) / 2
    bp = size("body", L)
    disp = _disp(n)
    dw = M.text_w(disp, bp * 1.2, True) + 12
    put_text(ctx, _s(n.get("label")), x, y, w - dw, bp * 1.3, bp, color(ctx, "ink", tone), bold=True, lh=1.0,
             valign="bottom")
    put_text(ctx, disp, x + w - dw, y - bp * 0.2, dw, bp * 1.5, int(bp * 1.2), color(ctx, "primary", tone), bold=True,
             align="right", valign="bottom", lh=1.0, font=ctx.latin or ctx.font)
    by = y + bp * 1.3 + 12
    bh = max(12, int(14 * LEVELS[L]))
    track = ctx.pal["soft"] if tone == "light" else mix("FFFFFF", ctx.pal["primary"], 0.7)
    ctx.slide.add_shape("roundRect", x=IN(x), y=IN(by), w=IN(w), h=IN(bh), rectRadius=IN(bh / 2),
                        fill={"color": track}, line={"type": "none"})
    p = _pct(n)
    if p is not None and p > 0:
        fw = w * min(1.0, p / 100.0)
        col = color(ctx, "primary", tone) if p >= float(n.get("good_at") or 0) else ctx.pal["warn"]
        ctx.slide.add_shape("roundRect", x=IN(x), y=IN(by), w=IN(max(bh, fw)), h=IN(bh), rectRadius=IN(bh / 2),
                            fill={"color": col}, line={"type": "none"})
        if p > 100:  # 超额：在 100% 处画目标刻度
            ctx.slide.add_shape("rect", x=IN(x + w * 100 / p - 1), y=IN(by - 6), w=IN(3), h=IN(bh + 12),
                                fill={"color": color(ctx, "ink", tone)}, line={"type": "none"})
    if _s(n.get("target")):
        sp = size("small", L)
        put_text(ctx, n["target"], x, by + bh + 8, w, sp * 1.3, sp, color(ctx, "muted", tone), lh=1.0)


def _ring_d(n, w, L):
    return min(w * 0.9, 300 * LEVELS[L])


def m_ring(n, w, L):
    d = _ring_d(n, w, L)
    h = d
    if _s(n.get("label")):
        h += 18 + M.text_h(n["label"], w, size("body", L), 1.3, True)
    return h


def d_ring(ctx, n, box, L, tone):
    from .engine.render import add_ring_segment
    x, y, w, h = box
    nat = m_ring(n, w, L)
    if h > nat:
        y += (h - nat) / 2
    d = _ring_d(n, w, L)
    cx, cy = x + w / 2, y + d / 2
    ro, ri = d / 2, d / 2 * 0.78
    track = ctx.pal["soft"] if tone == "light" else mix("FFFFFF", ctx.pal["primary"], 0.7)
    add_ring_segment(ctx.slide, cx, cy, ro, ri, 0, 359.9, track)
    p = _pct(n)
    if p is not None and p > 0.5:
        add_ring_segment(ctx.slide, cx, cy, ro, ri, -90, -90 + 360 * min(1.0, p / 100.0), color(ctx, "primary", tone))
    disp = _disp(n)
    vp = max(28, min(int(d * 0.26), int(ri * 1.7 / max(0.5, value_em(disp)))))
    put_text(ctx, disp, cx - ri, cy - vp * 0.62, ri * 2, vp * 1.25, vp, color(ctx, "ink", tone), bold=True,
             align="center", valign="middle", lh=1.0, font=ctx.latin or ctx.font)
    if _s(n.get("label")):
        bp = size("body", L)
        put_text(ctx, n["label"], x, y + d + 18, w, M.text_h(n["label"], w, bp, 1.3, True), bp, color(ctx, "ink", tone),
                 bold=True, align="center", lh=1.3)


MEASURE.update({"progress": m_progress, "ring": m_ring})
DRAW.update({"progress": d_progress, "ring": d_ring})
LEAVES = tuple(MEASURE)


# ════════════ 第三批元素：箭头流程、时间轴、排名横条、中心辐射、徽章 ════════════
def _its(n):
    out = []
    for it in n.get("items") or []:
        if isinstance(it, dict):
            d = {k: _s(it.get(k)) for k in ("label", "head", "text", "icon", "display")}
            d["value"] = it.get("value")
            out.append(d)
        elif _s(it):
            out.append({"label": "", "head": "", "text": _s(it), "icon": "", "display": "", "value": None})
    return out


def _flow_h(L):
    return max(84, int(104 * LEVELS[L]))


def _under_card(ctx, x, y, w, h):
    """流程 / 时间轴下方的说明区：按当前设计语言画底（浅色块 / 顶部细线 / 细框）"""
    from . import styles as STY
    P_ = ctx.pal
    st = (STY.CUR.get("cards") or {}).get("soft", "soft")
    if st == "rule":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(2), fill={"color": P_["ink"]}, line={"type": "none"})
    elif st == "fine":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"type": "none"},
                            line={"color": P_.get("accent") or P_["primary"], "width": 0.75})
    elif st == "bracket":
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": P_["soft"]}, line={"type": "none"})
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(28), h=IN(4), fill={"color": P_["primary"]}, line={"type": "none"})
    else:
        ctx.slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": P_["soft"]}, line={"type": "none"})


def m_flow(n, w, L):
    its = _its(n)
    if not its:
        return 0
    cw = w / len(its)
    bp = size("body", L)
    th = max((M.text_h(i["text"], cw - 28, bp, 1.35) for i in its), default=0)
    return _flow_h(L) + (24 + th if th else 0)


def d_flow(ctx, n, box, L, tone):
    x, y, w, h = box
    its = _its(n)
    if not its:
        return
    k = len(its)
    cw = w / k
    ch = _flow_h(L)
    hp, bp = size("lead", L), size("body", L)
    P_ = ctx.pal
    for i, it in enumerate(its):
        col = mix(P_["primary"], P_.get("secondary") or P_["primary"], i / max(1, k - 1) * 0.8)
        shape = "homePlate" if i == 0 else "chevron"
        ctx.slide.add_shape(shape, x=IN(x + i * cw), y=IN(y), w=IN(cw + (ch * 0.28 if i < k - 1 else 0)), h=IN(ch),
                            fill={"color": col}, line={"type": "none"}, adj={"adj": 28000})
        put_text(ctx, it["head"] or it["label"] or "%02d" % (i + 1), x + i * cw + (ch * 0.42 if i else 24), y,
                 cw - ch * 0.6, ch, hp, "FFFFFF", bold=True, valign="middle", lh=1.1)
        if it["text"]:
            ty, pad = y + ch + 24, 0
            if h - m_flow(n, w, L) > 60:  # 有富余高度：每步下面放一张说明卡，撑满版面
                pad = 22
                _under_card(ctx, x + i * cw + 6, y + ch + 18, cw - 12 - (6 if i < k - 1 else 0), h - ch - 18)
                ty = y + ch + 18 + pad + 4
            put_text(ctx, it["text"], x + i * cw + 14 + pad * 0.6, ty, cw - 28 - pad * 1.2, y + h - ty - pad, bp,
                     color(ctx, "ink", tone), lh=1.35, hl=hl_color(ctx, tone))


def m_timeline(n, w, L):
    its = _its(n)
    if not its:
        return 0
    cw = w / len(its)
    lp, hp, bp = size("lead", L), size("lead", L), size("body", L)
    hh = max((M.text_h(i["head"], cw - 24, hp, 1.25, True) for i in its), default=0)
    th = max((M.text_h(i["text"], cw - 24, bp, 1.35) for i in its), default=0)
    return lp * 1.3 + 64 + hh + (10 + th if th else 0)


def d_timeline(ctx, n, box, L, tone):
    x, y, w, h = box
    its = _its(n)
    if not its:
        return
    k = len(its)
    cw = w / k
    lp, hp, bp = size("lead", L), size("lead", L), size("body", L)
    nat = m_timeline(n, w, L)
    cards = h - nat > 60  # 富余高度：节点下方放说明卡撑满
    if h > nat and not cards:
        y += (h - nat) * 0.4
    ly = y + lp * 1.3 + 30
    P_ = ctx.pal
    ctx.slide.add_shape("rect", x=IN(x), y=IN(ly - 2), w=IN(w), h=IN(4), fill={"color": P_["line"]}, line={"type": "none"})
    for i, it in enumerate(its):
        cx = x + i * cw + 12
        put_text(ctx, it["label"] or "%02d" % (i + 1), cx, y, cw - 24, lp * 1.3, lp, color(ctx, "primary", tone),
                 bold=True, lh=1.0, valign="bottom", font=ctx.latin or ctx.font)
        r = 13
        last = i == k - 1
        ctx.slide.add_shape("ellipse", x=IN(cx), y=IN(ly - r), w=IN(r * 2), h=IN(r * 2),
                            fill={"color": P_["primary"] if last else "FFFFFF"},
                            line={"color": P_["primary"], "width": 2.5})
        ty = ly + 34
        if cards:
            _under_card(ctx, cx - 12 + 6, ly + 30, cw - 12, y + h - ly - 30)
            ty = ly + 30 + 24
            cx += 14
        if it["head"]:
            hh = M.text_h(it["head"], cw - 24 - (28 if cards else 0), hp, 1.25, True)
            put_text(ctx, it["head"], cx, ty, cw - 24 - (28 if cards else 0), hh, hp, color(ctx, "ink", tone), bold=True, lh=1.25)
            ty += hh + 10
        if it["text"]:
            put_text(ctx, it["text"], cx, ty, cw - 24 - (28 if cards else 0), max(10, y + h - ty - (20 if cards else 0)), bp,
                     color(ctx, "muted", tone), lh=1.35, hl=hl_color(ctx, tone))


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def m_hbars(n, w, L):
    return len(_its(n)) * size("body", L) * 2.3


def d_hbars(ctx, n, box, L, tone):
    x, y, w, h = box
    its = [i for i in _its(n) if _num(i["value"]) is not None]
    if not its:
        return
    bp = size("body", L)
    rh = max(bp * 2.3, h / len(its))
    lw = min(w * 0.3, max(M.text_w(i["label"], bp) for i in its) + 24)
    vw = max(M.text_w(i["display"] or str(i["value"]), bp, True) for i in its) + 24
    mx = max(_num(i["value"]) for i in its) or 1
    bw_max = w - lw - vw
    bh = max(14, bp * 0.8)
    P_ = ctx.pal
    hl = n.get("highlight")
    for k, it in enumerate(its):
        cy = y + k * rh
        v = _num(it["value"])
        put_text(ctx, it["label"], x, cy, lw - 16, rh, bp, color(ctx, "ink", tone), bold=True, valign="middle", lh=1.0)
        top = (hl is None and v == mx) or hl == k
        bw = max(6, bw_max * max(0, v) / mx)
        ctx.slide.add_shape("rect", x=IN(x + lw), y=IN(cy + (rh - bh) / 2), w=IN(bw), h=IN(bh),
                            fill={"color": P_["primary"] if top else mix(P_["primary"], "FFFFFF", 0.55)},
                            line={"type": "none"})
        put_text(ctx, it["display"] or str(it["value"]), x + lw + bw + 12, cy, vw, rh, bp,
                 color(ctx, "primary" if top else "ink", tone), bold=True, valign="middle", lh=1.0,
                 font=ctx.latin or ctx.font)


def d_hub(ctx, n, box, L, tone):
    import math
    x, y, w, h = box
    its = _its(n)
    if not its:
        return
    P_ = ctx.pal
    cx, cy = x + w / 2, y + h / 2
    d = min(h * 0.42, w * 0.22)
    k = len(its)
    rx, ry = w * 0.34, h * 0.36
    bw = min(400, w * 0.27)
    hp, bp = size("lead", L), size("body", L) - 2
    for i in range(k):
        a = math.radians(-90 + 360.0 * i / k)
        px, py = cx + rx * math.cos(a), cy + ry * math.sin(a)
        ctx.slide.add_shape("line", x=IN(min(cx, px)), y=IN(min(cy, py)), w=IN(abs(px - cx)), h=IN(abs(py - cy)),
                            line={"color": P_["line"], "width": 1.5}, flipH=(px < cx) != (py < cy))
    ctx.slide.add_shape("ellipse", x=IN(cx - d / 2 - 14), y=IN(cy - d / 2 - 14), w=IN(d + 28), h=IN(d + 28),
                        fill={"color": mix(P_["primary"], "FFFFFF", 0.85)}, line={"type": "none"})
    ctx.slide.add_shape("ellipse", x=IN(cx - d / 2), y=IN(cy - d / 2), w=IN(d), h=IN(d),
                        fill={"color": P_["primary"]}, line={"type": "none"})
    put_text(ctx, _s(n.get("center")) or "核心", cx - d * 0.42, cy - d * 0.42, d * 0.84, d * 0.84,
             max(26, min(size("h2", L), int(d * 0.84 / max(2, min(len(_s(n.get("center")) or "核心"), 6))))),
             "FFFFFF", bold=True, align="center", valign="middle", lh=1.15)
    for i, it in enumerate(its):
        a = math.radians(-90 + 360.0 * i / k)
        px, py = cx + rx * math.cos(a), cy + ry * math.sin(a)
        ip = 56
        right = math.cos(a) > 0.2
        left = math.cos(a) < -0.2
        bx = px - bw / 2 if not (left or right) else (px - ip / 2 if right else px - bw + ip / 2)
        al = "center" if not (left or right) else ("left" if right else "right")
        ctx.icon(it["icon"] or None, it["head"] + it["text"], px - ip / 2, py - ip / 2, ip, P_["primary"], "solid")
        hh = M.text_h(it["head"], bw - ip, hp, 1.2, True) if it["head"] else 0
        ty = py + ip / 2 + 8 if not (left or right) else py - (hh + bp * 2.6) / 2
        tx = bx if not (left or right) else (px + ip / 2 + 14 if right else bx - ip / 2 - 14)
        tw = bw if not (left or right) else bw - ip / 2
        if not (left or right) and math.sin(a) < 0:  # 正上方：文字放图标上方
            ty = py - ip / 2 - 8 - hh - bp * 2.8
        if it["head"]:
            put_text(ctx, it["head"], tx, ty, tw, hh, hp, color(ctx, "ink", tone), bold=True, align=al, lh=1.2)
        if it["text"]:
            put_text(ctx, it["text"], tx, ty + hh + 4, tw, bp * 2.8, bp, color(ctx, "muted", tone), align=al, lh=1.3,
                     hl=hl_color(ctx, tone))


def m_badge(n, w, L):
    return min(w, 120 * LEVELS[L])


def d_badge(ctx, n, box, L, tone):
    x, y, w, h = box
    d = min(w, 120 * LEVELS[L])
    cx, cy = x + w / 2, y + h / 2
    P_ = ctx.pal
    ctx.slide.add_shape("ellipse", x=IN(cx - d / 2), y=IN(cy - d / 2), w=IN(d), h=IN(d),
                        fill={"color": P_.get("accent") or P_["primary"]}, line={"color": "FFFFFF", "width": 4})
    put_text(ctx, _s(n.get("text")) or "VS", cx - d / 2, cy - d / 2, d, d, int(d * 0.36),
             P_.get("on_accent") or "FFFFFF", bold=True, align="center", valign="middle", lh=1.0,
             font=ctx.latin or ctx.font)


FLEX["hub"] = 560
MEASURE.update({"flow": m_flow, "timeline": m_timeline, "hbars": m_hbars, "hub": lambda n, w, L: FLEX["hub"],
                "badge": m_badge})
DRAW.update({"flow": d_flow, "timeline": d_timeline, "hbars": d_hbars, "hub": d_hub, "badge": d_badge})
LEAVES = tuple(MEASURE)


# ── 第四批：圆形节点串联（图标大圆 + 骑缝序号 + 连线），适合 3–5 个并列/递进要点 ──
def _orb_text(n, cw, L):
    its = _its(n)
    hp, bp = size("lead", L), size("body", L)
    hh = max((M.text_h(i["head"], cw - 24, hp, 1.25, True) for i in its if i["head"]), default=0)
    th = max((M.text_h(i["text"], cw - 24, bp, 1.35) for i in its if i["text"]), default=0)
    return hh, th


def _orb_d(n, w, L):
    k = max(1, len(_its(n)))
    return min(w / k * 0.5, 150 * LEVELS[L])


def m_orbs(n, w, L):
    its = _its(n)
    if not its:
        return 0
    cw = w / len(its)
    hh, th = _orb_text(n, cw, L)
    return _orb_d(n, w, L) + 30 + hh + (10 + th if th else 0)


def orbs_used(n, w, h, L):
    """长高后实际画出来的高度（给空白带检查用）"""
    nat = m_orbs(n, w, L)
    d = _orb_d(n, w, L)
    cw = w / max(1, len(_its(n)))
    d2 = min(d * 1.8, d + max(0.0, h - nat) * 0.75, cw * 0.62)
    return nat - d + d2


def d_orbs(ctx, n, box, L, tone):
    x, y, w, h = box
    its = _its(n)
    if not its:
        return
    from .engine.ooxml.util import mix as _mix
    k = len(its)
    cw = w / k
    hh, th = _orb_text(n, cw, L)
    nat = m_orbs(n, w, L)
    # 富余高度：大圆适度放大（最多 1.35 倍），其余均分到上下
    d = _orb_d(n, w, L)
    extra = max(0.0, h - nat)
    d2 = min(d * 1.8, d + extra * 0.75, cw * 0.62)
    y += max(0.0, (h - (nat - d + d2)) * 0.35)
    d = d2
    P_ = ctx.pal
    hp, bp = size("lead", L), size("body", L)
    cy = y + d / 2
    if k > 1:
        ctx.slide.add_shape("rect", x=IN(x + cw / 2), y=IN(cy - 1), w=IN(cw * (k - 1)), h=IN(2),
                            fill={"color": P_["line"]}, line={"type": "none"})
    from . import styles as STY
    lang = STY.CUR.get("id")
    for i, it in enumerate(its):
        cx = x + cw * i + cw / 2
        ring = P_.get("accent") if lang == "luxury" else P_["primary"]
        if lang in ("luxury", "editorial"):
            ctx.slide.add_shape("ellipse", x=IN(cx - d / 2), y=IN(y), w=IN(d), h=IN(d), fill={"color": "FFFFFF"},
                                line={"color": ring, "width": 1.25})
        else:
            ctx.slide.add_shape("ellipse", x=IN(cx - d / 2), y=IN(y), w=IN(d), h=IN(d),
                                fill={"color": _mix(P_["primary"], "FFFFFF", 0.88)}, line={"type": "none"})
            dd = d * 0.72
            ctx.slide.add_shape("ellipse", x=IN(cx - dd / 2), y=IN(cy - dd / 2), w=IN(dd), h=IN(dd),
                                fill={"color": "FFFFFF"}, line={"color": P_["primary"], "width": 2})
        ip = d * 0.36
        ctx.icon(it["icon"] or None, it["head"] + it["text"], cx - ip / 2, cy - ip / 2, ip,
                 P_.get("accent_text") if lang == "luxury" else P_["primary"], "glyph")
        b = max(34, d * 0.24)  # 骑缝序号
        bx, by = cx + d * 0.354 - b / 2, y + d * 0.146 - b / 2
        ctx.slide.add_shape("ellipse", x=IN(bx), y=IN(by), w=IN(b), h=IN(b), fill={"color": ring},
                            line={"color": "FFFFFF", "width": 2.5})
        put_text(ctx, "%02d" % (i + 1), bx, by, b, b, max(14, int(b * 0.42)), "FFFFFF", bold=True, align="center",
                 valign="middle", lh=1.0, font=ctx.latin or ctx.font)
        ty = y + d + 30
        if it["head"]:
            put_text(ctx, it["head"], x + cw * i + 12, ty, cw - 24, hh, hp, color(ctx, "ink", tone), bold=True,
                     align="center", lh=1.25)
            ty += hh + 10
        if it["text"]:
            put_text(ctx, it["text"], x + cw * i + 12, ty, cw - 24, max(10, y + h - ty), bp, color(ctx, "muted", tone),
                     align="center", lh=1.35, hl=hl_color(ctx, tone))


MEASURE["orbs"] = m_orbs
DRAW["orbs"] = d_orbs
LEAVES = tuple(MEASURE)
