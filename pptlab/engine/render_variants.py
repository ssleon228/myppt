"""版式变体（设计系统 v2）：从旧项目 api/pptx-variants.ts 逐函数移植。

网格：左右边距 96，内容宽 1728；页眉页内容区 y 200-980，无页眉页 y 96-990。
字号：display 160-240 · h1 64-88 · h2 44 · lead 36 · body 32 · small 26 · caption 22（px，导出 pt = px/2）。
原则：少卡片多留白，细线分隔代替方框；每页一个视觉焦点；深色整版页给整套节奏。

旧版用 SVG 图片画的深色渐变底、圆环、半透明压暗层、箭头带，这里全部是原生形状
（渐变填充 + 裁剪到页面内的圆弧路径），PowerPoint 里可编辑。
"""
import math
import re

from .ooxml.geom import Path
from .ooxml.util import mix as _mix, js_round
from . import fontmetrics

W = 1920
H = 1080
M = 96
BELOW = dict(x=0, y=145, w=1920, h=935)
WARN = "C8553D"


def P(px):
    return px / 2.0


def IN(px):
    return px / 144.0


def mix(a, b, t):
    return _mix(a, b, t)


class Kit:
    """变体渲染上下文（对应 TS VariantKit）"""

    def __init__(self, C, font, latin, locked, logo_white, show_page_no, add_header, add_footer, add_chart,
                 resolve_image, icon_badge=None, icons_on=False):
        self.C = C
        self.FONT = font
        self.LATIN = latin
        self.locked = locked
        self.logo_white = logo_white
        self.show_page_no = show_page_no
        self.add_header = add_header
        self.add_footer = add_footer
        self.add_chart = add_chart
        self.resolve_image = resolve_image
        self.icon_badge = icon_badge
        self.icons_on = icons_on

    def clone(self, **kw):
        k = Kit.__new__(Kit)
        k.__dict__.update(self.__dict__)
        k.__dict__.update(kw)
        return k


# ── 文本测量 ──────────────────────────────────────────────
_measure = {"font": "微软雅黑", "latin": None}


def ch_w(ch):
    return fontmetrics.char_em(ch, _measure["font"], _measure["latin"])


def line_count(text, box_w, px):
    lines = 0
    for para in str(text or "").split("\n"):
        cur = 0.0
        n = 1
        for ch in para:
            w = ch_w(ch) * px
            if cur + w > box_w:
                n += 1
                cur = w
            else:
                cur += w
        lines += n
    return lines


SINGLE = 1.25


def fit_px(text, box_w, box_h, mx, mn, lh=1.3, max_lines=99):
    px = mx
    while px > mn:
        n = line_count(text, box_w * 0.96, px)
        if n <= max_lines and n * px * lh * SINGLE <= box_h:
            return px
        px -= 2
    return mn


def text_h(text, box_w, px, lh=1.3):
    return line_count(text, box_w * 0.96, px) * px * lh * SINGLE


def balanced_w(text, w, px):
    lines = line_count(text, w * 0.96, px)
    if lines <= 1:
        return w
    em = sum(ch_w(ch) for ch in str(text))
    bw = min(w, ((math.ceil(em / lines) + 1) * px) / 0.96)
    return w if line_count(text, bw * 0.96, px) > lines else bw


_VAL_RE = re.compile(r"^([^0-9+\-−≤≥<>~.]*)([+\-−≤≥<>~]?[0-9][0-9,.]*%?)(.*)$", re.S)


def value_runs(value, px, color):
    v = str(value or "")
    m = _VAL_RE.match(v.strip())
    if not m:
        return [{"text": v, "options": {"fontSize": P(px), "color": color, "bold": True}}]
    small = max(24, js_round(px * 0.42))
    runs = []
    if m.group(1):
        runs.append({"text": m.group(1), "options": {"fontSize": P(small), "color": color, "bold": True}})
    runs.append({"text": m.group(2), "options": {"fontSize": P(px), "color": color, "bold": True}})
    if m.group(3):
        runs.append({"text": m.group(3), "options": {"fontSize": P(small), "color": color, "bold": True}})
    return runs


def value_em(value):
    v = str(value or "")
    m = _VAL_RE.match(v.strip())

    def em(t):
        return sum(ch_w(ch) for ch in t)

    if not m:
        return em(v)
    return em(m.group(2)) + (em(m.group(1)) + em(m.group(3))) * 0.42


def fmt_num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(v):
        return ""
    if abs(v) >= 100:
        return "{:,}".format(int(js_round(v)))
    r = js_round(v * 100) / 100.0
    return str(int(r)) if r == int(r) else str(r)


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_pictographic(s):
    for ch in s:
        o = ord(ch)
        if 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or o in (0xFE0F, 0x2B50):
            return True
    return False


def _item_text(i):
    if isinstance(i, str):
        return i
    if isinstance(i, dict):
        return str(i.get("text") or "")
    return ""


# ── 绘制原语 ─────────────────────────────────────────────
class Draw:
    def __init__(self, slide, k):
        self.s = slide
        self.k = k

    def rect(self, x, y, w, h, color, transparency=0):
        self.s.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": color, "transparency": transparency},
                         line={"type": "none"})

    def hline(self, x, y, w, color, weight_px=2, dash=None):
        ln = {"color": color, "width": P(weight_px)}
        if dash:
            ln["dashType"] = dash
        self.s.add_shape("line", x=IN(x), y=IN(y), w=IN(w), h=0, line=ln)

    def vline(self, x, y, h, color, weight_px=2, transparency=0):
        self.s.add_shape("line", x=IN(x), y=IN(y), w=0, h=IN(h),
                         line={"color": color, "width": P(weight_px), "transparency": transparency})

    def circle(self, cx, cy, r, fill, stroke=None):
        self.s.add_shape("ellipse", x=IN(cx - r), y=IN(cy - r), w=IN(r * 2), h=IN(r * 2),
                         fill={"color": fill} if fill else {"type": "none"},
                         line={"color": stroke["color"], "width": P(stroke["px"]),
                               "transparency": stroke.get("transparency", 0)} if stroke else {"type": "none"})

    def text(self, t, x, y, w, h, px, color, bold=False, align="left", valign="top", lh=1.3, spacing=None, wrap=True,
             transparency=0, fill=None):
        o = dict(x=IN(x), y=IN(y), w=IN(w), h=IN(h), fontSize=P(px), color=color, bold=bool(bold), fontFace=self.k.FONT,
                 align=align, valign=valign, margin=0, lineSpacingMultiple=lh)
        if spacing:
            o["charSpacing"] = spacing
        if wrap is False:
            o["wrap"] = False
        if transparency:
            o["transparency"] = transparency
        if fill:
            o["fill"] = {"color": fill}
        self.s.add_text(t, **o)


# ── 裁剪到矩形内的圆 / 圆弧（替代 SVG 画布裁剪） ──────────────

def _clip_circle_poly(cx, cy, r, box):
    x0, y0, x1, y1 = box
    pts = []
    for i in range(360):
        a = math.radians(i)
        pts.append((min(x1, max(x0, cx + r * math.cos(a))), min(y1, max(y0, cy + r * math.sin(a)))))
    return pts


def clipped_disc(slide, cx, cy, r, box, color, alpha):
    """圆盘与矩形的交集（凸形 ∩ 矩形 = 边界点夹到矩形内）"""
    x0, y0, x1, y1 = box
    if cx - r >= x0 and cx + r <= x1 and cy - r >= y0 and cy + r <= y1:
        slide.add_shape("ellipse", x=IN(cx - r), y=IN(cy - r), w=IN(2 * r), h=IN(2 * r),
                        fill={"color": color, "transparency": (1 - alpha) * 100}, line={"type": "none"})
        return
    p = Path().polygon(_clip_circle_poly(cx, cy, r, box))
    bx0, by0, bx1, by1 = p.bbox()
    if bx1 - bx0 < 1 or by1 - by0 < 1:
        return
    slide.add_custom(p, local=(bx0, by0, bx1 - bx0, by1 - by0), x=IN(bx0), y=IN(by0), w=IN(bx1 - bx0), h=IN(by1 - by0),
                     fill={"color": color, "transparency": (1 - alpha) * 100}, line={"type": "none"})


def clipped_ring(slide, cx, cy, r, box, color, alpha, width_px=2):
    """圆周落在矩形内的弧段（描边，无填充）"""
    x0, y0, x1, y1 = box
    inside = []
    for i in range(360):
        a = math.radians(i + 0.5)
        px_, py_ = cx + r * math.cos(a), cy + r * math.sin(a)
        inside.append(x0 <= px_ <= x1 and y0 <= py_ <= y1)
    if all(inside):
        slide.add_shape("ellipse", x=IN(cx - r), y=IN(cy - r), w=IN(2 * r), h=IN(2 * r), fill={"type": "none"},
                        line={"color": color, "width": P(width_px), "transparency": (1 - alpha) * 100})
        return
    if not any(inside):
        return
    # 找出连续的「在内」区间
    start = inside.index(False)
    runs = []
    cur = None
    for j in range(1, 361):
        i = (start + j) % 360
        if inside[i]:
            if cur is None:
                cur = [start + j, start + j]
            else:
                cur[1] = start + j
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)
    p = Path()
    for a0, a1 in runs:
        p.arc(cx, cy, r, r, a0, a1 + 1, connect=False)
    bx0, by0, bx1, by1 = p.bbox()
    slide.add_custom(p, local=(bx0, by0, max(1, bx1 - bx0), max(1, by1 - by0)), x=IN(bx0), y=IN(by0),
                     w=IN(max(1, bx1 - bx0)), h=IN(max(1, by1 - by0)), fill={"type": "none"},
                     line={"color": color, "width": P(width_px), "transparency": (1 - alpha) * 100})


def dark_background(slide, k, ink, rings=True):
    top = mix(ink, "FFFFFF", 0.06)
    b = BELOW if k.locked else dict(x=0, y=0, w=W, h=H)
    # 渐变按整页坐标计算（与旧版 viewBox 一致）：锁定模式只铺 banner 下方
    slide.add_shape("rect", x=IN(b["x"]), y=IN(b["y"]), w=IN(b["w"]), h=IN(b["h"]),
                    fill={"type": "grad", "ang": 45, "stops": [{"pos": 0, "color": top}, {"pos": 100, "color": ink}]},
                    line={"type": "none"})
    if rings:
        box = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
        clipped_ring(slide, 1760, 920, 460, box, k.C.primary, 0.35)
        clipped_ring(slide, 1760, 920, 330, box, k.C.primary, 0.18)
        clipped_disc(slide, 1760, 920, 200, box, k.C.primary, 0.10)


def _lum(h):
    out = []
    for i in (0, 2, 4):
        v = int(h[i:i + 2], 16) / 255.0
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def safe_on_white(hx, deep):
    c = hx
    t = 0.15
    while 1.05 / (_lum(c) + 0.05) < 3 and t <= 0.9:
        c = mix(hx, deep, t)
        t += 0.15
    return c


def ink_of(k):
    return mix(k.C.deep, "000000", 0.42)


def title_block(d, kicker, title, x, y, w, on_dark, k, max_px=64, max_lines=2):
    C = k.C
    cy = y
    if kicker:
        d.rect(x, cy + 8, 40, 4, C.primary)
        d.text(kicker, x + 56, cy - 4, w - 56, 32, px=24, color=mix(C.primary, "FFFFFF", 0.35) if on_dark else C.primary,
               bold=True, spacing=2, wrap=False)
        cy += 56
    px = fit_px(title, w, max_lines * max_px * 1.25, max_px, 40, 1.25, max_lines)
    th = text_h(title, w, px, 1.25)
    bw = balanced_w(title, w, px)
    if title:
        d.text(title, x, cy, bw, th + 8, px=px, color="FFFFFF" if on_dark else C.deep, bold=True, lh=1.25)
    return cy + th + 8


def dark_page_chrome(slide, d, k, page, page_no):
    if k.logo_white and not k.locked:
        slide.add_image(path=k.logo_white, x=IN(1810), y=IN(33), w=IN(77), h=IN(81.3))
    muted = mix(ink_of(k), "FFFFFF", 0.5)
    if page.note:
        d.text(page.note, M, 1012, 1500, 36, px=22, color=muted, valign="middle")
    if k.show_page_no:
        d.text(str(page_no), 1724, 1012, 100, 36, px=22, color=muted, align="right", valign="middle", wrap=False)


def _icon(k, d, icon, text, x, y, size, color, style="glyph"):
    """变体里的图标：glyph=只画图标本身；soft/solid=圆形徽章"""
    if k.icon_badge is None:
        return False
    return k.icon_badge(d.s, icon, text, x, y, size, color, style=style)


# ════════════════════════════════════════════════════
# 变体实现
# ════════════════════════════════════════════════════

def statement(slide, d, k, page, kicker=None):
    ink = ink_of(k)
    dark_background(slide, k, ink)
    quote = str(page.quote or page.title or "").strip()
    kick = kicker or (page.title if page.title and page.title != quote else None)
    if kick and not k.locked:
        title_block(d, kick, "", M, 120, 1200, True, k)
    px = fit_px(quote, 1400, 440 if k.locked else 480, 88, 52, 1.25, 4)
    bw = balanced_w(quote, 1400, px)
    qh = text_h(quote, bw, px, 1.25)
    y0 = max(250, 570 - qh / 2 - 40) if k.locked else max(300, 520 - qh / 2)
    d.text(quote, M, y0, bw, qh + 16, px=px, color="FFFFFF", bold=True, lh=1.25)
    ry = y0 + qh + 56
    d.rect(M, ry, 96, 6, k.C.primary)
    if page.subtitle:
        d.text(page.subtitle, M, ry + 32, 1200, 44, px=28, color=mix(ink, "FFFFFF", 0.65))


def fullbleed(slide, d, k, page, kicker=None):
    abs_ = k.resolve_image(page.image) if page.image else None
    B = BELOW if k.locked else dict(x=0, y=0, w=W, h=H)
    if abs_:
        slide.add_image(path=abs_, x=IN(B["x"]), y=IN(B["y"]), w=IN(B["w"]), h=IN(B["h"]), sizing={"type": "cover"})
    else:
        dark_background(slide, k, ink_of(k), False)
    ink = ink_of(k)
    slide.add_shape("rect", x=IN(B["x"]), y=IN(B["y"]), w=IN(B["w"]), h=IN(B["h"]), line={"type": "none"},
                    fill={"type": "grad", "ang": 0, "stops": [{"pos": 0, "color": ink, "alpha": 0.82},
                                                              {"pos": 62, "color": ink, "alpha": 0.15},
                                                              {"pos": 100, "color": ink, "alpha": 0}]})
    slide.add_shape("rect", x=IN(B["x"]), y=IN(B["y"]), w=IN(B["w"]), h=IN(B["h"]), line={"type": "none"},
                    fill={"type": "grad", "ang": 270, "stops": [{"pos": 0, "color": ink, "alpha": 0.75},
                                                                {"pos": 55, "color": ink, "alpha": 0}]})
    if k.locked:
        cap = str(page.caption or "").strip()
        if not cap:
            return
        px = fit_px(cap, 1150, 2 * 56 * 1.3, 56, 36, 1.3, 2)
        ch = text_h(cap, 1150, px, 1.3)
        d.rect(M, 930 - ch - 40, 72, 6, k.C.primary)
        d.text(cap, M, 930 - ch, 1150, ch + 8, px=px, color="FFFFFF", bold=True, lh=1.3)
        return
    title = page.title or ""
    cap = str(page.caption or "").strip()
    bw = 1150
    px = fit_px(title, bw, 2 * 84 * 1.22, 84, 52, 1.22, 2)
    th = text_h(title, bw, px, 1.22)
    cap_h = text_h(cap, bw, 30, 1.45) if cap else 0
    bottom = 930
    ty = bottom - cap_h - (36 if cap else 0) - th
    if kicker:
        d.rect(M, ty - 52, 40, 4, k.C.primary)
        d.text(kicker, M + 56, ty - 64, 900, 32, px=24, color="FFFFFF", bold=True, spacing=2, wrap=False)
    d.text(title, M, ty, bw, th + 8, px=px, color="FFFFFF", bold=True, lh=1.22)
    if cap:
        d.text(cap, M, bottom - cap_h, bw, cap_h + 8, px=30, color="FFFFFF", lh=1.45, transparency=12)


_page_no = {"n": 0}


def split(slide, d, k, page, kicker=None):
    ink = ink_of(k)
    PW = 700
    slide.add_shape("rect", x=0, y=0, w=IN(PW), h=IN(H), line={"type": "none"},
                    fill={"type": "grad", "ang": 59,
                          "stops": [{"pos": 0, "color": mix(ink, "FFFFFF", 0.07)}, {"pos": 100, "color": ink}]})
    box = (0, 0, PW, H)
    clipped_ring(slide, PW, H, 380, box, k.C.primary, 0.35)
    clipped_disc(slide, PW, H, 250, box, k.C.primary, 0.12)
    title_block(d, kicker, page.title or "", M, 150, PW - M - 72, True, k, max_px=60, max_lines=5)
    items = [t for t in (_item_text(i) for i in (page.get("items") or [])) if t][:5]
    n = len(items)
    x0 = PW + 112
    xw = W - x0 - M
    top, bottom = 150, 950
    row_h = (bottom - top) / float(n)
    px = min(fit_px(t, xw - 120, row_h - 56, 36, 26, 1.4, 3) for t in items)
    for i, t in enumerate(items):
        y = top + i * row_h
        if i > 0:
            d.hline(x0, y, xw, k.C.line, 2)
        d.text(str(i + 1).zfill(2), x0, y + 28, 100, row_h - 56, px=48, color=k.C.primary, bold=True, wrap=False,
               valign="middle", lh=1)
        d.text(t, x0 + 120, y + 28, xw - 120, row_h - 56, px=px, color=k.C.deep, lh=1.4, valign="middle")
    if page.note:
        d.text(page.note, x0, 1012, xw - 140, 36, px=22, color=k.C.gray, valign="middle")
    if k.show_page_no and _page_no["n"]:
        d.text(str(_page_no["n"]), 1724, 1012, 100, 36, px=22, color=k.C.gray, align="right", valign="middle", wrap=False)


def numbered(d, k, page):
    items = [t for t in (_item_text(i) for i in (page.get("items") or [])) if t][:6]
    cols = 1 if len(items) <= 3 else 2
    rows = int(math.ceil(len(items) / float(cols)))
    gx = 96
    cw = (W - 2 * M - (cols - 1) * gx) / float(cols)
    rh = min((960 - 230) / float(rows), 300)
    top = 200 + (780 - rh * rows) / 2 + 20
    px = min(fit_px(t, cw - 128, rh - 72, 40 if len(items) <= 4 else 34, 26, 1.45, 4) for t in items)
    for i, t in enumerate(items):
        c = 0 if cols == 1 else i % cols
        r = i if cols == 1 else i // cols
        x = M + c * (cw + gx)
        y = top + r * rh
        d.hline(x, y, cw, k.C.line, 2)
        d.rect(x, y - 3, 64, 6, k.C.primary)
        d.text(str(i + 1).zfill(2), x, y + 32, 120, 72, px=56, color=k.C.primary, bold=True, wrap=False)
        d.text(t, x + 128, y + 40, cw - 128, rh - 72, px=px, color=k.C.text, lh=1.45)


def list_column(d, k, items, x, y, w, h, head):
    d.text(head, x, y, w, 40, px=26, color=k.C.gray, bold=True, spacing=2)
    cy = y + 64
    px = min(fit_px(t, w, (h - 64) / float(len(items)) - 40, 32, 24, 1.45, 4) for t in items)
    for t in items:
        d.hline(x, cy, w, k.C.line, 2)
        th = text_h(t, w, px, 1.45)
        d.text(t, x, cy + 22, w, th + 8, px=px, color=k.C.text, lh=1.45)
        cy += th + 56


def conclusion(d, k, text, y):
    d.hline(M, y, W - 2 * M, k.C.line, 2)
    d.text("结论", M, y + 28, 120, 44, px=28, color=k.C.primary, bold=True, wrap=False)
    px = fit_px(text, W - 2 * M - 140, 80, 30, 24, 1.4, 2)
    d.text(text, M + 140, y + 28, W - 2 * M - 140, 84, px=px, color=k.C.deep, lh=1.4)


def _tks(page, n=99):
    return [t for t in (page.takeaways or []) if str(t or "").strip()][:n]


def hero(d, k, page):
    stats = (page.stats or [])[:2]
    tks = _tks(page, 3)
    if len(stats) == 1:
        s = stats[0]
        left_w = 980 if tks else 1728
        px = min(280, math.floor((left_w * 0.92) / max(1, value_em(s.value))))
        d.text(value_runs(s.value, px, k.C.primary), M, 290, left_w, px * 1.15, px=px, color=k.C.primary, bold=True,
               wrap=False, valign="bottom", lh=1)
        d.rect(M, 290 + px * 1.15 + 36, 96, 6, k.C.deep)
        d.text(s.label, M, 290 + px * 1.15 + 72, left_w, 120, px=40, color=k.C.deep, bold=True, lh=1.35)
        if tks:
            list_column(d, k, tks, 1180, 300, W - M - 1180, 600, "解读")
        return
    cw = (W - 2 * M - 96) / 2.0
    for i, s in enumerate(stats):
        x = M + i * (cw + 96)
        px = min(220, math.floor((cw * 0.92) / max(1, value_em(s.value))))
        d.text(value_runs(s.value, px, k.C.primary if i == 0 else k.C.deep), x, 300, cw, px * 1.15, px=px,
               color=k.C.primary, bold=True, wrap=False, valign="bottom", lh=1)
        d.rect(x, 300 + px * 1.15 + 32, 96, 6, k.C.primary if i == 0 else k.C.deep)
        d.text(s.label, x, 300 + px * 1.15 + 64, cw, 110, px=36, color=k.C.text, lh=1.35)
    d.vline(W / 2.0, 320, 420, k.C.line, 2)
    if tks:
        conclusion(d, k, "；".join(tks), 860)


def stat_row(slide, d, k, page, dark, kicker=None):
    stats = (page.stats or [])[:4]
    n = len(stats)
    if not n:
        return
    tks = _tks(page, 2)
    ink = ink_of(k)
    top = 200
    if dark:
        dark_background(slide, k, ink)
        if k.locked:
            top = 220
        else:
            tb = title_block(d, kicker, page.title or "", M, 120, 1500, True, k)
            top = max(300, tb + 60)
    cw = (W - 2 * M) / float(n)
    pad = 0 if n == 1 else 56
    em = max(value_em(s.value) for s in stats)
    px = min(190 if n <= 3 else 150, math.floor(((cw - 2 * pad) * 0.94) / max(1, em)))
    lab_px = 32 if n <= 3 else 28
    lab_h = max(text_h(s.label, cw - pad * 1.5, lab_px, 1.4) for s in stats)
    block_h = 24 + px * 1.1 + 28 + lab_h
    area_top = top if dark else 200
    area_h = (840 if dark else (840 if tks else 980)) - area_top
    y0 = area_top + max(0, (area_h - block_h) / 2)
    num_color = "FFFFFF" if dark else k.C.deep
    lab_color = mix(ink, "FFFFFF", 0.7) if dark else k.C.gray
    for i, s in enumerate(stats):
        x = M + i * cw
        if i > 0:
            d.vline(x, y0, block_h, "FFFFFF" if dark else k.C.line, 2, 80 if dark else 0)
        tx = x + (0 if i == 0 else pad)
        d.rect(tx, y0, 56, 6, k.C.primary if i == 0 else (mix(k.C.primary, "FFFFFF", 0.3) if dark else k.C.blue))
        col = k.C.primary if (i == 0 and not dark) else num_color
        d.text(value_runs(s.value, px, col), tx, y0 + 24, cw - pad, px * 1.1, px=px, color=col, bold=True, wrap=False,
               lh=1, valign="bottom")
        d.text(s.label, tx, y0 + 24 + px * 1.1 + 28, cw - pad * 1.5, lab_h + 8, px=lab_px, color=lab_color, lh=1.4)
    if tks:
        if dark:
            t = "；".join(tks)
            d.hline(M, 860, W - 2 * M, "FFFFFF", 1)
            d.text(t, M, 888, 1500, 80, px=30, color=mix(k.C.primary, "FFFFFF", 0.45), bold=True, lh=1.4)
        else:
            conclusion(d, k, "；".join(tks), 860)


def annotated(d, k, page):
    c = page.chart
    cats = [str(x) for x in (c.categories or [])[:8]]
    s0 = (c.series or [None])[0]
    vals = []
    for i in range(len(cats)):
        v = (s0.get("values") or [])[i] if s0 and i < len(s0.get("values") or []) else None
        vals.append(v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0)
    hi = min(len(cats) - 1, max(0, c.highlight if c.highlight is not None else len(cats) - 1))
    unit = c.unit or ""
    gx, gw, g_top, g_base = M, 1180, 300, 880
    vmax = max(vals + [0]) or 1
    vmin = min(vals + [0])
    span = (vmax - vmin) or 1

    def y_of(v):
        return g_base - ((v - vmin) / float(span)) * (g_base - g_top)

    slot = gw / float(len(cats))
    muted = mix(k.C.line, k.C.gray, 0.25)
    if c.title or unit:
        d.text("%s%s" % (c.title or "", "（%s）" % unit if unit else ""), gx, 214, gw, 40, px=26, color=k.C.gray, bold=True)
    d.hline(gx, g_base, gw, k.C.gray, 2)
    if c.kind == "line":
        pts = [(gx + slot * (i + 0.5), y_of(v)) for i, v in enumerate(vals)]
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            d.s.add_shape("line", x=IN(min(a[0], b[0])), y=IN(min(a[1], b[1])), w=IN(abs(b[0] - a[0])),
                          h=IN(max(0.01, abs(b[1] - a[1]))), flipV=b[1] < a[1],
                          line={"color": k.C.primary if i <= hi else muted, "width": P(6)})
        for i, (px_, py_) in enumerate(pts):
            if i == hi:
                d.circle(px_, py_, 22, k.C.primary)
                d.circle(px_, py_, 36, None, {"color": k.C.primary, "px": 3, "transparency": 50})
            else:
                d.circle(px_, py_, 10, "FFFFFF", {"color": k.C.primary if i < hi else muted, "px": 5})
            d.text(fmt_num(vals[i]), px_ - slot / 2, py_ - 72, slot, 40, px=32 if i == hi else 24,
                   color=k.C.primary if i == hi else k.C.gray, bold=i == hi, align="center", wrap=False)
    else:
        bw = min(120, slot * 0.56)
        for i, v in enumerate(vals):
            x = gx + slot * (i + 0.5) - bw / 2
            y = y_of(max(v, 0))
            h = max(2, abs(y_of(v) - y_of(0)))
            d.rect(x, y if v >= 0 else y_of(0), bw, h, k.C.primary if i == hi else muted)
            d.text(fmt_num(v), x - 40, (y if v >= 0 else y_of(0)) - 52, bw + 80, 40, px=32 if i == hi else 24,
                   color=k.C.primary if i == hi else k.C.gray, bold=i == hi, align="center", wrap=False)
    for i, cat in enumerate(cats):
        d.text(cat, gx + slot * i, g_base + 20, slot, 40, px=24, color=k.C.deep if i == hi else k.C.gray, bold=i == hi,
               align="center", wrap=False)
    hx = gx + slot * (hi + 0.5)
    hy = y_of(vals[hi])
    RX = 1380
    d.hline(hx + 40, hy, RX - hx - 72, k.C.primary, 2, "dash")
    rw = W - M - RX
    val = fmt_num(vals[hi])
    em = sum(ch_w(ch) for ch in val)
    vpx = min(150, math.floor((rw * 0.75) / max(1, em)))
    vy = max(260, min(hy - vpx * 0.6, 480))
    d.text(cats[hi], RX, vy - 52, rw, 40, px=26, color=k.C.gray, bold=True, wrap=False)
    d.text([{"text": val, "options": {"fontSize": P(vpx), "color": k.C.primary, "bold": True}},
            {"text": " %s" % unit if unit else "", "options": {"fontSize": P(32), "color": k.C.primary, "bold": True}}],
           RX, vy, rw, vpx * 1.1, px=vpx, color=k.C.primary, bold=True, wrap=False, lh=1, valign="bottom")
    cy = vy + vpx * 1.1 + 32
    note = str(c.annotation or "").strip() or (str((page.takeaways or [""])[0] or "").strip() if page.takeaways else "")
    if note:
        px = fit_px(note, rw, 160, 36, 26, 1.35, 3)
        th = text_h(note, rw, px, 1.35)
        d.text(note, RX, cy, rw, th + 8, px=px, color=k.C.deep, bold=True, lh=1.35)
        cy += th + 40
    rest = [t for t in (page.takeaways or []) if str(t or "").strip() and str(t).strip() != note][:2]
    for t in rest:
        if cy > 900:
            break
        d.hline(RX, cy, rw, k.C.line, 2)
        th = text_h(t, rw, 26, 1.45)
        d.text(t, RX, cy + 18, rw, th + 8, px=26, color=k.C.text, lh=1.45)
        cy += th + 48


def before_after(d, k, page):
    L, Rr = page.left, page.right
    if not L or not Rr:
        return
    cw = (W - 2 * M - 120) / 2.0

    def pts_h(pts):
        return sum(text_h(t, cw - 168, 32, 1.4) + 36 for t in (pts or [])[:5])

    h = min(740, max(460, 260 + max(pts_h(L.points), pts_h(Rr.points)) + 40))
    top = 200 + (780 - h) / 2
    xs = [M, M + cw + 120]
    sides = [(L, k.C.soft, k.C.deep, k.C.text, "现状", k.C.gray),
             (Rr, k.C.primary, "FFFFFF", "FFFFFF", "目标", mix(k.C.primary, "FFFFFF", 0.7))]
    for i, (s, bg, tc, body, tag, tag_c) in enumerate(sides):
        x = xs[i]
        d.rect(x, top, cw, h, bg)
        d.text(s.nameEn or tag, x + 64, top + 64, cw - 128, 36, px=24, color=tag_c, bold=True, spacing=2, wrap=False)
        d.text(s.name, x + 64, top + 108, cw - 128, 72, px=fit_px(s.name, cw - 128, 72, 48, 32, 1.2, 1), color=tc,
               bold=True, wrap=False)
        pts = (s.points or [])[:5]
        if not pts:
            continue
        avail = h - 260
        px = min(fit_px(t, cw - 168, avail / float(len(pts)) - 24, 32, 24, 1.4, 3) for t in pts)
        cy = top + 230
        for t in pts:
            d.text("—" if i == 0 else "✓", x + 64, cy, 40, px * 1.4, px=px, color=k.C.gray if i == 0 else "FFFFFF",
                   bold=True, wrap=False)
            th = text_h(t, cw - 168, px, 1.4)
            d.text(t, x + 112, cy, cw - 176, th + 8, px=px, color=body, lh=1.4)
            cy += max(th, px * 1.4) + 36
    cx = W / 2.0
    cy = top + h / 2
    d.circle(cx, cy, 52, "FFFFFF", {"color": k.C.line, "px": 2})
    d.text("→", cx - 52, cy - 52, 104, 104, px=56, color=k.C.primary, bold=True, align="center", valign="middle",
           wrap=False, lh=1)


def roadmap(d, k, page):
    if page.type == "steps":
        nodes = [dict(label="STEP %d" % (i + 1), title=s.title or "", desc=s.desc) for i, s in enumerate(page.steps or [])]
    else:
        nodes = [dict(label=t.label or "", title=t.title or "", desc=t.desc) for t in (page.timeline or [])]
    n = min(6, len(nodes))
    if not n:
        return
    nodes = nodes[:n]
    slot = (W - 2 * M) / float(n)
    tw = slot - 48
    title_px = min(fit_px(t["title"], tw, 2 * 40 * 1.3, 40, 28, 1.3, 2) for t in nodes)
    desc_px = min((fit_px(t["desc"], tw, 240, 30, 22, 1.45, 5) if t["desc"] else 30) for t in nodes)
    below = max(text_h(t["title"], tw, title_px, 1.3) + (20 + text_h(t["desc"], tw, desc_px, 1.45) if t["desc"] else 0)
                for t in nodes)
    block_h = 120 + 56 + below
    line_y = 200 + max(60, (780 - block_h) / 2) + 120
    d.hline(M, line_y, W - 2 * M, k.C.line, 6)
    d.hline(M, line_y, slot * (n - 1) + 18, k.C.primary, 6)
    for i, t in enumerate(nodes):
        x = M + slot * i
        cx = x + 18
        last = i == n - 1
        d.circle(cx, line_y, 24 if last else 16, k.C.primary if last else "FFFFFF", {"color": k.C.primary, "px": 6})
        lpx = min(48, fit_px(t["label"], tw, 64, 48, 28, 1, 1))
        d.text(t["label"], x, line_y - 112, tw, 64, px=lpx, color=k.C.primary if last else k.C.deep, bold=True,
               wrap=False, valign="bottom", lh=1)
        th = text_h(t["title"], tw, title_px, 1.3)
        d.text(t["title"], x, line_y + 56, tw, th + 8, px=title_px, color=k.C.deep, bold=True, lh=1.3)
        if t["desc"]:
            d.text(t["desc"], x, line_y + 56 + th + 20, tw, 300, px=desc_px, color=k.C.gray, lh=1.45)


def chevron(d, k, page):
    steps = (page.steps or [])[:6]
    n = len(steps)
    if not n:
        return
    gap, tip = 12, 44
    w = (W - 2 * M - (n - 1) * gap) / float(n)
    desc_px = min((fit_px(s.desc, w - 48, 320, 34, 24, 1.5, 6) if s.desc else 34) for s in steps)
    desc_h = max((text_h(s.desc, w - 48, desc_px, 1.5) if s.desc else 0) for s in steps)
    band_h = 190
    y0 = 200 + max(40, (780 - band_h - 56 - desc_h) / 2)
    for i, st in enumerate(steps):
        x = M + i * (w + gap)
        t = 1 if n == 1 else i / float(n - 1)
        fill = mix(mix(k.C.primary, "FFFFFF", 0.55), k.C.primary, t)
        if i == n - 1:
            pts = [(0, 0), (w, 0), (w, band_h), (0, band_h)] + ([(tip, band_h / 2.0)] if i else [])
        else:
            pts = [(0, 0), (w - tip, 0), (w, band_h / 2.0), (w - tip, band_h), (0, band_h)] + \
                  ([(tip, band_h / 2.0)] if i else [])
        p = Path().polygon(pts)
        d.s.add_custom(p, local=(0, 0, w, band_h), x=IN(x), y=IN(y0), w=IN(w), h=IN(band_h), fill={"color": fill},
                       line={"type": "none"})
        on_dark = t > 0.45
        tx = x + (tip + 12 if i else 32)
        tw = w - (tip + 12 if i else 32) - tip - 8
        d.text(str(i + 1).zfill(2), tx, y0 + 28, tw, 44, px=32, color="FFFFFF" if on_dark else k.C.deep, bold=True,
               wrap=False, transparency=20)
        tpx = fit_px(st.title, tw, 90, 44, 26, 1.2, 2)
        d.text(st.title, tx, y0 + 80, tw, 96, px=tpx, color="FFFFFF" if on_dark else k.C.deep, bold=True, lh=1.2)
        if st.desc:
            d.hline(x + 24, y0 + band_h + 32, 48, k.C.primary, 4)
            d.text(st.desc, x + 24, y0 + band_h + 56, w - 48, desc_h + 16, px=desc_px, color=k.C.text, lh=1.5)


def lined(d, k, page):
    cols = (page.cols or [])[:4]
    n = len(cols)
    if not n:
        return
    gap = 72
    cw = (W - 2 * M - (n - 1) * gap) / float(n)
    head_px = min(fit_px(c.heading, cw, 2 * 46 * 1.25 * 1.25, 46, 30, 1.25, 2) for c in cols)
    body_px = min(fit_px(c.text, cw, 400, 34, 24, 1.55, 9) for c in cols)
    hh = max(text_h(c.heading, cw, head_px, 1.25) for c in cols)
    bh = max(text_h(c.text, cw, body_px, 1.55) for c in cols)
    block_h = 136 + hh + 28 + bh
    y0 = 200 + max(40, (780 - block_h) / 2)
    for i, c in enumerate(cols):
        x = M + i * (cw + gap)
        col = k.C.primary if i == 0 else k.C.deep
        d.hline(x, y0, cw, k.C.line, 2)
        d.rect(x, y0 - 3, 72, 6, col)
        icon = c.icon or ""
        short_mark = icon and len(icon) <= 2 and not _is_pictographic(icon)
        drawn = False
        if not short_mark and (icon or k.icons_on):
            drawn = _icon(k, d, icon or None, c.heading, x, y0 + 32, 76, col, style="glyph")
        if not drawn:
            mark = icon if short_mark else str(i + 1).zfill(2)
            d.text(mark, x, y0 + 28, cw, 84, px=72, color=col, bold=True, wrap=False, lh=1)
        d.text(c.heading, x, y0 + 136, cw, hh + 8, px=head_px, color=k.C.deep, bold=True, lh=1.25)
        d.text(c.text, x, y0 + 136 + hh + 28, cw, bh + 16, px=body_px, color=k.C.text, lh=1.55)


def group_cols(d, k, page):
    groups = (page.groups or [])[:4]
    n = len(groups)
    gap = 72
    cw = (W - 2 * M - (n - 1) * gap) / float(n)
    items = [_item_text(t) if not isinstance(t, str) else t for g in groups for t in (g.get("items") or [])]
    px = min([fit_px(t, cw - 36, 200, 34, 24, 1.45, 4) for t in items] + [34])

    def col_h(g):
        return sum(text_h(_item_text(t), cw - 36, px, 1.45) + 28 for t in (g.get("items") or []))

    block_h = 140 + max(col_h(g) for g in groups)
    y0 = 200 + max(30, (780 - block_h) / 2)
    for i, g in enumerate(groups):
        x = M + i * (cw + gap)
        col = k.C.primary if i == 0 else k.C.deep
        d.rect(x, y0, cw, 8, k.C.primary if i == 0 else mix(k.C.deep, "FFFFFF", 0.15 * i))
        drawn = False
        if g.icon is not None or k.icons_on:
            drawn = _icon(k, d, g.icon, g.heading, x, y0 + 32, 56, col, style="glyph")
        if not drawn:
            d.text(str(i + 1).zfill(2), x, y0 + 32, 90, 56, px=40, color=col, bold=True, wrap=False, lh=1)
        d.text(g.heading, x + 80, y0 + 32, cw - 80, 56, px=fit_px(g.heading, cw - 80, 60, 42, 28, 1.2, 1), color=k.C.deep,
               bold=True, wrap=False, lh=1.2)
        cy = y0 + 132
        for it in g.get("items") or []:
            t = _item_text(it)
            d.rect(x, cy + px * 0.55, 12, 12, k.C.primary)
            th = text_h(t, cw - 36, px, 1.45)
            d.text(t, x + 36, cy, cw - 36, th + 8, px=px, color=k.C.text, lh=1.45)
            cy += th + 28


_NUM_RE = re.compile(r"^[\s+\-−]?[\d,.]+\s*(%|亿|万|元|bp|BP|pct|个|户|笔)?$")


def _is_num(v):
    return bool(_NUM_RE.match(str(v if v is not None else "").strip()))


def _cell(r, ci):
    return str(r[ci]) if ci < len(r) and r[ci] is not None else ""


def _line_b(c, pt):
    none = {"type": "none"}
    return [none, none, {"type": "solid", "color": c, "pt": pt}, none]


def clean_table(d, k, page):
    headers = page.headers or []
    rows = (page.rows or [])[:9]
    nc = len(headers)
    if not nc:
        return
    num_col = [bool(rows) and sum(1 for r in rows if _is_num(_cell(r, ci))) >= len(rows) * 0.6 for ci in range(nc)]
    tks = _tks(page)
    bottom = 820 if tks else 960
    row_h = min(84, (bottom - 230 - 72) / float(max(1, len(rows))))
    px = 30 if row_h >= 70 else 26

    def al(ci):
        return "left" if ci == 0 else ("right" if num_col[ci] else "center")

    head = [{"text": h, "options": {"bold": True, "color": k.C.gray, "fontSize": P(24), "align": al(ci),
                                    "border": _line_b(k.C.deep, 2)}} for ci, h in enumerate(headers)]
    body = []
    for ri, r in enumerate(rows):
        last = ri == len(rows) - 1
        body.append([{"text": _cell(r, ci), "options": {
            "bold": ci == 0, "color": k.C.deep if ci == 0 else k.C.text, "fontSize": P(px), "align": al(ci),
            "border": _line_b(k.C.deep if last else k.C.line, 1.5 if last else 0.75)}} for ci in range(nc)])
    first_w = min(520, (W - 2 * M) * (0.4 if nc <= 3 else 0.28))
    rest_w = (W - 2 * M - first_w) / float(max(1, nc - 1))
    d.s.add_table([head] + body, x=IN(M), y=IN(230), w=IN(W - 2 * M),
                  colW=[IN(first_w if ci == 0 else rest_w) for ci in range(nc)],
                  rowH=[IN(72)] + [IN(row_h)] * len(rows), fontFace=k.FONT, valign="middle", margin=[0, 0.12, 0, 0.12])
    if tks:
        conclusion(d, k, "；".join(tks[:2]), 860)


def halfbleed(d, k, page):
    abs_ = k.resolve_image(page.image) if page.image else None
    right = page.direction == "right"
    IW = 860
    ix = W - IW if right else 0
    if abs_:
        d.s.add_image(path=abs_, x=IN(ix), y=IN(145), w=IN(IW), h=IN(H - 145), sizing={"type": "cover"})
    else:
        d.rect(ix, 145, IW, H - 145, k.C.soft)
    items = [t for t in (_item_text(i) for i in (page.get("items") or [])) if t][:5]
    x0 = M if right else IW + 96
    xw = W - IW - 96 - M
    px = min([fit_px(t, xw - 72, 160, 36, 24, 1.45, 3) for t in items] + [36])
    total = sum(text_h(t, xw - 72, px, 1.45) + 44 for t in items) - 44
    cy = 200 + max(30, (780 - total) / 2)
    for i, t in enumerate(items):
        th = text_h(t, xw - 72, px, 1.45)
        d.text(str(i + 1).zfill(2), x0, cy, 64, px * 1.4, px=js_round(px * 1.1), color=k.C.primary, bold=True, wrap=False)
        d.text(t, x0 + 72, cy, xw - 72, th + 8, px=px, color=k.C.deep, lh=1.45)
        cy += th + 22
        if i < len(items) - 1:
            d.hline(x0, cy, xw, k.C.line, 2)
        cy += 22
    if page.caption:
        d.text(page.caption, ix + 48, H - 92, IW - 96, 44, px=22, color="FFFFFF", transparency=10)


def combo_hero(d, k, page):
    stats = (page.stats or [])[:3]
    LW = 560
    n = len(stats)
    rh = min(240, 740.0 / max(1, n))
    y0 = 200 + (780 - rh * n) / 2
    for i, s in enumerate(stats):
        y = y0 + i * rh
        if i > 0:
            d.hline(M, y, LW - 40, k.C.line, 2)
        px = min(120 if i == 0 else 96, math.floor(((LW - 60) * 0.92) / max(1, value_em(s.value))))
        d.text(value_runs(s.value, px, k.C.primary if i == 0 else k.C.deep), M, y + 28, LW - 40, px * 1.1, px=px,
               color=k.C.primary, bold=True, wrap=False, lh=1, valign="bottom")
        d.text(s.label, M, y + 28 + px * 1.1 + 12, LW - 40, 80, px=26, color=k.C.gray, lh=1.35)
    d.vline(M + LW, 230, 720, k.C.line, 2)
    if page.chart:
        k.add_chart(d.s, page.chart, {"x": M + LW + 64, "y": 220, "w": W - M - (M + LW + 64), "h": 740})


def versus(d, k, page):
    L, Rr = page.left, page.right
    if not L or not Rr:
        return
    cw = (W - 2 * M - 200) / 2.0
    xs = [M, M + cw + 200]
    colors = [k.C.deep, k.C.primary]
    pts_all = ((L.points or []) + (Rr.points or []))[:10]
    px = min([fit_px(t, cw - 40, 150, 36, 24, 1.45, 3) for t in pts_all] + [36])

    def col_h(pts):
        return sum(text_h(t, cw - 40, px, 1.45) + 40 for t in (pts or [])[:5])

    block_h = 170 + max(col_h(L.points), col_h(Rr.points))
    y0 = 200 + max(30, (780 - block_h) / 2)
    for i, side in enumerate((L, Rr)):
        x = xs[i]
        d.rect(x, y0, cw, 10, colors[i])
        if side.nameEn:
            d.text(str(side.nameEn).upper(), x, y0 + 32, cw, 32, px=22, color=k.C.gray, bold=True, spacing=2, wrap=False)
        d.text(side.name, x, y0 + (68 if side.nameEn else 40), cw, 72, px=fit_px(side.name, cw, 72, 56, 32, 1.2, 1),
               color=colors[i], bold=True, wrap=False, lh=1.2)
        cy = y0 + 170
        for t in (side.points or [])[:5]:
            th = text_h(t, cw - 40, px, 1.45)
            d.rect(x, cy + px * 0.55, 12, 12, colors[i])
            d.text(t, x + 40, cy, cw - 40, th + 8, px=px, color=k.C.text, lh=1.45)
            cy += th + 20
            d.hline(x + 40, cy, cw - 40, k.C.line, 1)
            cy += 20
    cx = W / 2.0
    d.vline(cx, y0 + 20, block_h - 20, k.C.line, 2)
    d.circle(cx, y0 + block_h / 2, 48, "FFFFFF", {"color": k.C.line, "px": 2})
    d.text("VS", cx - 48, y0 + block_h / 2 - 48, 96, 96, px=32, color=k.C.gray, bold=True, align="center",
           valign="middle", wrap=False, lh=1)


def chapter_bold(slide, d, k, page):
    ink = ink_of(k)
    dark_background(slide, k, ink)
    num = str(page.part if page.part is not None else 1).zfill(2)
    d.text(num, M - 12, 170, 900, 420, px=400, color=k.C.primary, bold=True, wrap=False, lh=1, valign="bottom")
    d.rect(M, 640, 120, 8, k.C.primary)
    d.text(page.partText or "PART %s" % ("" if page.part is None else page.part), M, 690, 900, 40, px=28,
           color=mix(k.C.primary, "FFFFFF", 0.4), bold=True, spacing=4, wrap=False)
    px = fit_px(page.title or "", 1500, 130, 104, 60, 1.2, 1)
    d.text(page.title or "", M, 744, 1500, 140, px=px, color="FFFFFF", bold=True, wrap=False, lh=1.2)
    if page.subtitle:
        d.text(page.subtitle, M, 890, 1400, 48, px=30, color=mix(ink, "FFFFFF", 0.65))
    if k.logo_white:
        slide.add_image(path=k.logo_white, x=IN(1810), y=IN(33), w=IN(77), h=IN(81.3))


_PCT_RE = re.compile(r"([+\-−]?\d[\d,]*\.?\d*)\s*%")


def pct_of(s):
    m = _PCT_RE.search(str(s if s is not None else ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "").replace("−", "-"))
    except ValueError:
        return None


def scorecard(d, k, page):
    gs = (page.gauges or [])[:6]
    tks = _tks(page)
    top = 250
    bottom = 820 if tks else 960
    row_h = min(140, (bottom - top) / float(len(gs)))
    vals = [_num(g.value) for g in gs]
    vmax = min(200, max([120] + [v * 1.08 for v in vals]))
    LX, LW, VX, VW, BX, BW = M, 440, M + 460, 260, M + 780, 700
    TX = BX + BW + 48
    TW = W - M - TX
    tick = BX + (100 / vmax) * BW
    d.text("目标 100%", tick - 100, top - 50, 200, 32, px=22, color=k.C.gray, align="center", wrap=False)
    for i, g in enumerate(gs):
        v = vals[i]
        y = top + i * row_h
        cy = y + row_h / 2
        color = k.C.primary if v >= 100 else WARN
        if i > 0:
            d.hline(M, y, W - 2 * M, k.C.line, 1.5)
        lpx = fit_px(g.label, LW, row_h * 0.8, 34, 24, 1.25, 2)
        d.text(g.label, LX, y, LW, row_h, px=lpx, color=k.C.deep, bold=True, valign="middle", lh=1.25)
        disp = g.display or "%s%%" % fmt_num(v)
        vpx = min(js_round(row_h * 0.5), 68, math.floor((VW * 0.95) / max(1, value_em(disp))))
        d.text(value_runs(disp, vpx, color), VX, y, VW, row_h, px=vpx, color=color, bold=True, align="right",
               valign="middle", wrap=False, lh=1)
        bh = min(24, row_h * 0.2)
        d.rect(BX, cy - bh / 2, BW, bh, k.C.soft)
        d.rect(BX, cy - bh / 2, max(4, (min(v, vmax) / vmax) * BW), bh, color)
        if g.target:
            d.text(g.target, TX, y, TW, row_h, px=fit_px(g.target, TW, row_h * 0.8, 26, 20, 1.3, 2), color=k.C.gray,
                   valign="middle", lh=1.3)
    d.vline(tick, top - 8, row_h * len(gs) + 8, k.C.deep, 2)
    if tks:
        conclusion(d, k, "；".join(tks[:2]), 860)


def ranking(d, k, page):
    c = page.chart
    s0 = (c.series or [None])[0]
    raw = []
    for i, cat in enumerate((c.categories or [])[:16]):
        v = (s0.get("values") or [])[i] if s0 and i < len(s0.get("values") or []) else None
        raw.append(dict(cat=str(cat), v=v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0, i=i))
    hi_src = min(len(raw) - 1, max(0, c.highlight if c.highlight is not None else 0))
    asc = c.sort == "asc"
    items = sorted(raw, key=lambda x: x["v"] if asc else -x["v"])
    hi = next((j for j, x in enumerate(items) if x["i"] == hi_src), -1)
    n = len(items)
    unit = c.unit or ""
    top = 250
    row_h = min(64, 700.0 / n)
    NX, NW, BX = M + 64, 230, M + 312
    BWmax = 1220 - 312 - 140
    vmax = max([x["v"] for x in items] + [0]) or 1
    avg = sum(x["v"] for x in items) / float(n)
    muted = mix(k.C.line, k.C.gray, 0.15)
    pct_u = "%" if unit == "%" else ""

    def r1(v):
        return fmt_num(v) if abs(v) >= 100 else fmt_num(js_round(v * 10) / 10.0)

    px = max(20, min(28, js_round(row_h * 0.46)))
    if c.title or unit:
        d.text("%s%s" % (c.title or "", "（%s）" % unit if unit else ""), M, 196, 1100, 40, px=24, color=k.C.gray, bold=True)
    tint = mix(k.C.primary, "FFFFFF", 0.88)
    ax = BX + (max(0, avg) / vmax) * BWmax
    if hi >= 0:
        d.rect(M - 16, top + hi * row_h + 2, 1220 - M + 32 + 16, row_h - 4, tint)
    d.s.add_shape("line", x=IN(ax), y=IN(top - 10), w=0, h=IN(row_h * n + 10),
                  line={"color": k.C.deep, "width": P(2), "dashType": "dash"})
    d.text("均值 %s%s" % (r1(avg), pct_u), ax - 100, top + row_h * n + 6, 200, 32, px=22, color=k.C.deep, align="center",
           wrap=False)
    for r, x in enumerate(items):
        y = top + r * row_h
        is_hi = r == hi
        d.text(str(r + 1), M, y, 52, row_h, px=px, color=k.C.primary if is_hi else k.C.gray, bold=True, align="right",
               valign="middle", wrap=False)
        d.text(x["cat"], NX, y, NW, row_h, px=px, color=k.C.deep if is_hi else k.C.text, bold=is_hi, align="right",
               valign="middle", wrap=False)
        bw = max(3, (max(0, x["v"]) / vmax) * BWmax)
        bh = max(8, row_h * 0.5)
        d.rect(BX, y + (row_h - bh) / 2, bw, bh, k.C.primary if is_hi else muted)
        label = fmt_num(x["v"])
        lw = sum(ch_w(ch) for ch in label) * px + 16
        d.text(label, BX + bw + 8, y + row_h * 0.18, lw, row_h * 0.64, px=px, color=k.C.primary if is_hi else k.C.gray,
               bold=is_hi, valign="middle", wrap=False, fill=tint if is_hi else "FFFFFF")
    RX = 1340
    rw = W - M - RX
    d.vline(RX - 56, top, row_h * n, k.C.line, 2)
    hx = items[hi] if hi >= 0 else None
    d.text(hx["cat"] if hx else "", RX, top, rw, 44, px=30, color=k.C.deep, bold=True, wrap=False)
    d.text([{"text": "第", "options": {"fontSize": P(40), "color": k.C.primary, "bold": True}},
            {"text": str(hi + 1), "options": {"fontSize": P(150), "color": k.C.primary, "bold": True}},
            {"text": " / %d" % n, "options": {"fontSize": P(40), "color": k.C.gray, "bold": True}}],
           RX, top + 56, rw, 170, px=150, color=k.C.primary, bold=True, wrap=False, lh=1, valign="bottom")
    gap = (hx["v"] - avg) if hx else 0
    d.text("%s%s · %s均值 %s%s" % (fmt_num(hx["v"] if hx else 0), pct_u or (" %s" % unit if unit else ""),
                                  "高于" if gap >= 0 else "低于", r1(abs(gap)), " 个百分点" if pct_u else ""),
           RX, top + 240, rw, 40, px=26, color=k.C.primary if gap >= 0 else WARN, bold=True, wrap=False)
    cy = top + 312
    notes = [str(t).strip() for t in [c.annotation] + list(page.takeaways or []) if t and str(t).strip()][:3]
    for i, t in enumerate(notes):
        if cy > 900:
            break
        d.hline(RX, cy, rw, k.C.line, 2)
        tp = fit_px(t, rw, 150, 32, 24, 1.4, 3) if i == 0 else fit_px(t, rw, 120, 26, 22, 1.45, 3)
        th = text_h(t, rw, tp, 1.4 if i == 0 else 1.45)
        d.text(t, RX, cy + 18, rw, th + 8, px=tp, color=k.C.deep if i == 0 else k.C.text, bold=i == 0,
               lh=1.4 if i == 0 else 1.45)
        cy += th + 48


_NEG_RE = re.compile(r"隐忧|风险|短板|问题|不足|下滑|承压|警示")


def metric(d, k, page):
    cols = (page.cols or [])[:4]
    n = len(cols)
    gap = 40
    cw = (W - 2 * M - (n - 1) * gap) / float(n)
    pad = 48
    iw = cw - 2 * pad
    neg = bool(_NEG_RE.search(page.title or ""))
    accent = WARN if neg else k.C.primary
    vw = iw - (56 if (k.icons_on or any(c.icon for c in cols)) else 0)  # 右上角图标位
    vpx = min([120] + [math.floor((vw * 0.95) / max(1, value_em(c.value or "—"))) for c in cols])
    head_px = min(fit_px(c.heading, iw, 2 * 40 * 1.25 * 1.25, 40, 28, 1.25, 2) for c in cols)
    body_px = min(fit_px(c.text, iw, 330, 30, 22, 1.55, 8) for c in cols)
    hh = max(text_h(c.heading, iw, head_px, 1.25) for c in cols)
    bh = max(text_h(c.text, iw, body_px, 1.55) for c in cols)
    card_h = min(760, pad + vpx * 1.1 + 40 + hh + 24 + bh + pad)
    y0 = 200 + max(24, (780 - card_h) / 2)
    for i, c in enumerate(cols):
        x = M + i * (cw + gap)
        col = accent if i == 0 else k.C.deep
        d.rect(x, y0, cw, card_h, k.C.soft)
        d.rect(x, y0, cw, 8, col)
        v = str(c.value or "").strip() or str(i + 1).zfill(2)
        has_icon = (c.icon and not (len(c.icon) <= 2 and not _is_pictographic(c.icon))) or k.icons_on
        if has_icon:
            _icon(k, d, c.icon or None, c.heading, x + cw - pad - 48, y0 + pad - 8, 48, col, style="glyph")
        d.text(value_runs(v, vpx, col), x + pad, y0 + pad, iw - (56 if has_icon else 0), vpx * 1.1, px=vpx, color=accent,
               bold=True, wrap=False, lh=1, valign="bottom")
        cy = y0 + pad + vpx * 1.1 + 24
        d.hline(x + pad, cy, 64, col, 4)
        cy += 16
        d.text(c.heading, x + pad, cy, iw, hh + 8, px=head_px, color=k.C.deep, bold=True, lh=1.25)
        cy += hh + 24
        d.text(c.text, x + pad, cy, iw, bh + 16, px=body_px, color=k.C.text, lh=1.55)


_RATE_H = re.compile(r"率|完成")
_HI_ROW = re.compile(r"武汉|本行|我行|本部")


def heat_table(d, k, page):
    headers = page.headers or []
    rows = (page.rows or [])[:12]
    nc = len(headers)
    if page.highlightRow is not None:
        hi_row = page.highlightRow
    else:
        hi_row = next((ri for ri, r in enumerate(rows) if _HI_ROW.search(_cell(r, 0))), -1)
    num_col = [bool(rows) and sum(1 for r in rows if _is_num(_cell(r, ci))) >= len(rows) * 0.6 for ci in range(nc)]
    rate_col = []
    for ci, h in enumerate(headers):
        ok = num_col[ci] and (bool(_RATE_H.search(str(h))) or all(
            (not _cell(r, ci)) or _cell(r, ci).strip().endswith("%") for r in rows))
        if ok:
            ps = [p for p in (pct_of(_cell(r, ci)) for r in rows) if p is not None]
            ok = any(v >= 100 for v in ps) and any(v < 100 for v in ps)
        rate_col.append(ok)
    tks = _tks(page)
    bottom = 820 if tks else 960
    row_h = min(80, (bottom - 230 - 72) / float(max(1, len(rows))))
    px = 30 if row_h >= 70 else (26 if row_h >= 56 else 22)
    tint = mix(k.C.primary, "FFFFFF", 0.86)

    def al(ci):
        return "left" if ci == 0 else ("right" if num_col[ci] else "center")

    head = [{"text": h, "options": {"bold": True, "color": "FFFFFF", "fill": {"color": k.C.deep}, "fontSize": P(24),
                                    "align": al(ci), "border": _line_b(k.C.deep, 0)}} for ci, h in enumerate(headers)]
    body = []
    for ri, r in enumerate(rows):
        row = []
        last = ri == len(rows) - 1
        for ci in range(nc):
            t = _cell(r, ci)
            p = pct_of(t) if rate_col[ci] else None
            color = (k.C.primary if p >= 100 else WARN) if p is not None else (k.C.deep if ci == 0 else k.C.text)
            o = {"bold": ci == 0 or ri == hi_row or p is not None, "color": color, "fontSize": P(px), "align": al(ci),
                 "border": _line_b(k.C.deep if last else k.C.line, 1.5 if last else 0.75)}
            if ri == hi_row:
                o["fill"] = {"color": tint}
            row.append({"text": t, "options": o})
        body.append(row)
    first_w = min(440, (W - 2 * M) * (0.4 if nc <= 3 else 0.24))
    rest_w = (W - 2 * M - first_w) / float(max(1, nc - 1))
    d.s.add_table([head] + body, x=IN(M), y=IN(230), w=IN(W - 2 * M),
                  colW=[IN(first_w if ci == 0 else rest_w) for ci in range(nc)],
                  rowH=[IN(68)] + [IN(row_h)] * len(rows), fontFace=k.FONT, valign="middle", margin=[0, 0.14, 0, 0.14])
    if 0 <= hi_row < len(rows):
        d.rect(M - 14, 230 + 68 + hi_row * row_h, 6, row_h, k.C.primary)
    if any(rate_col):
        ly = 182
        d.rect(W - M - 380, ly + 10, 14, 14, k.C.primary)
        d.text("≥100% 达标", W - M - 356, ly, 160, 34, px=20, color=k.C.gray, valign="middle", wrap=False)
        d.rect(W - M - 180, ly + 10, 14, 14, WARN)
        d.text("<100% 未达标", W - M - 156, ly, 160, 34, px=20, color=k.C.gray, valign="middle", wrap=False)
    if tks:
        conclusion(d, k, "；".join(tks[:2]), 860)


def step_grid(d, k, page):
    steps = (page.steps or [])[:6]
    n = len(steps)
    cols_n = n if n <= 3 else 2
    rows_n = int(math.ceil(n / float(cols_n)))
    gx, gy = 72, 40
    cw = (W - 2 * M - (cols_n - 1) * gx) / float(cols_n)
    ch = (740 - (rows_n - 1) * gy) / float(rows_n)
    use_icon = k.icons_on or any(s.icon for s in steps)
    tw = cw - 132 - (64 if use_icon else 0)
    tpx = min(fit_px(s.title, tw, 2 * 40 * 1.25 * 1.25, 40, 28, 1.25, 2) for s in steps)
    dpx = min(fit_px(s.desc or "", cw - 132, ch - 120, 30, 22, 1.5, 6) for s in steps)
    for i, s in enumerate(steps):
        x = M + (i % cols_n) * (cw + gx)
        y = 220 + (i // cols_n) * (ch + gy)
        d.hline(x, y, cw, k.C.line, 2)
        d.rect(x, y - 3, 96, 6, k.C.primary if i == 0 else k.C.deep)
        d.text(str(i + 1).zfill(2), x, y + 28, 112, 96, px=80, color=k.C.primary if i == 0 else mix(k.C.deep, "FFFFFF", 0.1),
               bold=True, wrap=False, lh=1)
        if use_icon:
            _icon(k, d, s.icon, s.title, x + cw - 52, y + 30, 52, k.C.primary if i == 0 else k.C.deep, style="glyph")
        th = text_h(s.title, tw, tpx, 1.25)
        d.text(s.title, x + 132, y + 32, tw, th + 8, px=tpx, color=k.C.deep, bold=True, lh=1.25)
        if s.desc:
            d.text(s.desc, x + 132, y + 32 + th + 16, cw - 132, ch - th - 60, px=dpx, color=k.C.text, lh=1.5)


def dashboard(d, k, page):
    stats = (page.stats or [])[:5]
    main, rest = stats[0], stats[1:]
    tks = _tks(page)
    PX, PW, PY, PH = M, 700, 220, 740
    d.rect(PX, PY, PW, PH, mix(k.C.primary, "FFFFFF", 0.9))
    d.rect(PX, PY, 10, PH, k.C.primary)
    ip = 64
    d.text(main.label, PX + ip, PY + 64, PW - 2 * ip, 90, px=fit_px(main.label, PW - 2 * ip, 90, 34, 24, 1.3, 2),
           color=k.C.deep, bold=True, lh=1.3)
    vpx = min(200, math.floor(((PW - 2 * ip) * 0.92) / max(1, value_em(main.value))))
    d.text(value_runs(main.value, vpx, k.C.primary), PX + ip, PY + 170, PW - 2 * ip, vpx * 1.15, px=vpx,
           color=k.C.primary, bold=True, wrap=False, lh=1, valign="bottom")
    if tks:
        ty = PY + 170 + vpx * 1.15 + 48
        d.hline(PX + ip, ty, 96, k.C.primary, 4)
        tp = fit_px(tks[0], PW - 2 * ip, PY + PH - ty - 80, 32, 24, 1.45, 5)
        d.text(tks[0], PX + ip, ty + 32, PW - 2 * ip, PY + PH - ty - 64, px=tp, color=k.C.deep, lh=1.45)
    RX = PX + PW + 96
    RW = W - M - RX
    cn = 1 if len(rest) <= 2 else 2
    rn = int(math.ceil(len(rest) / float(cn)))
    cw = (RW - (cn - 1) * 72) / float(cn)
    rh = (560 if len(tks) > 1 else PH) / float(max(1, rn))
    spx = min([104, js_round(rh * 0.42)] + [math.floor((cw * 0.92) / max(1, value_em(s.value))) for s in rest])
    for i, s in enumerate(rest):
        x = RX + (i % cn) * (cw + 72)
        y = PY + (i // cn) * rh
        d.hline(x, y, cw, k.C.line, 2)
        d.text(value_runs(s.value, spx, k.C.deep), x, y + 32, cw, spx * 1.15, px=spx, color=k.C.deep, bold=True,
               wrap=False, lh=1, valign="bottom")
        d.text(s.label, x, y + 32 + spx * 1.15 + 12, cw, rh - spx * 1.15 - 56,
               px=fit_px(s.label, cw, rh - spx * 1.15 - 56, 28, 20, 1.35, 3), color=k.C.gray, lh=1.35)
    if len(tks) > 1:
        ty = PY + 600
        d.hline(RX, ty, RW, k.C.deep, 2)
        t = "；".join(tks[1:3])
        d.text(t, RX, ty + 28, RW, PH - 628, px=fit_px(t, RW, PH - 640, 30, 22, 1.45, 4), color=k.C.text, lh=1.45)


# ════════════════════════════════════════════════════

def render_variant(slide, k, page, variant, page_no, kicker=None):
    """按变体渲染一页；返回 False 表示该变体不适用（调用方走原结构化版式）"""
    _measure["font"] = k.FONT or "微软雅黑"
    _measure["latin"] = k.LATIN
    _page_no["n"] = page_no if k.show_page_no else 0
    dk = k  # 深色页用原主色
    C2 = type(k.C)(dict(k.C))
    C2["primary"] = safe_on_white(k.C.primary, k.C.deep)
    C2["blue"] = safe_on_white(k.C.blue, k.C.deep)
    k = k.clone(C=C2)
    d = Draw(slide, k)

    def with_header(fn):
        k.add_header(slide, page.title)
        fn()
        k.add_footer(slide, page.note, page_no)
        return True

    if variant == "chevron":
        return bool(page.steps) and with_header(lambda: chevron(d, k, page))
    if variant == "lined":
        return bool(page.cols) and with_header(lambda: lined(d, k, page))
    if variant == "groupcols":
        return bool(page.groups) and with_header(lambda: group_cols(d, k, page))
    if variant == "clean":
        return bool(page.headers) and with_header(lambda: clean_table(d, k, page))
    if variant == "halfbleed":
        if not page.get("items"):
            return False
        k.add_header(slide, page.title)
        halfbleed(d, k, page)
        return True
    if variant == "comboHero":
        return bool(page.stats) and bool(page.chart) and with_header(lambda: combo_hero(d, k, page))
    if variant == "versus":
        return bool(page.left and page.right) and with_header(lambda: versus(d, k, page))
    if variant == "bold":
        if page.type != "chapter" or k.locked:
            return False
        chapter_bold(slide, Draw(slide, dk), dk, page)
        return True
    if variant == "statement":
        if not (page.quote or page.title):
            return False
        if k.locked:
            k.add_header(slide, page.title)
        statement(slide, Draw(slide, dk), dk, page, kicker)
        dark_page_chrome(slide, d, k, page, page_no)
        return True
    if variant == "fullbleed":
        fk = dk.clone(locked=False)
        fullbleed(slide, Draw(slide, fk), fk, page, kicker)
        pg = type(page)(dict(page))
        pg["note"] = None
        dark_page_chrome(slide, d, fk, pg, page_no)
        return True
    if variant == "split":
        if not page.get("items"):
            return False
        if k.locked:
            return with_header(lambda: numbered(d, k, page))
        split(slide, d, k, page, kicker)
        if k.logo_white:
            slide.add_image(path=k.logo_white, x=IN(M), y=IN(960), w=IN(58), h=IN(61))
        return True
    if variant == "band":
        if not page.stats:
            return False
        if k.locked:
            k.add_header(slide, page.title)
        stat_row(slide, Draw(slide, dk), dk, page, True, kicker)
        dark_page_chrome(slide, d, k, page, page_no)
        return True
    if variant == "numbered":
        return bool(page.get("items")) and with_header(lambda: numbered(d, k, page))
    if variant == "hero":
        return bool(page.stats) and with_header(lambda: hero(d, k, page))
    if variant == "row":
        return bool(page.stats) and with_header(lambda: stat_row(slide, d, k, page, False))
    if variant == "annotated":
        return bool(page.chart and page.chart.categories) and with_header(lambda: annotated(d, k, page))
    if variant == "beforeafter":
        return bool(page.left and page.right) and with_header(lambda: before_after(d, k, page))
    if variant == "roadmap":
        return bool(page.timeline or page.steps) and with_header(lambda: roadmap(d, k, page))
    if variant == "scorecard":
        return bool(page.gauges) and with_header(lambda: scorecard(d, k, page))
    if variant == "ranking":
        ok = page.chart and len(page.chart.categories or []) >= 3 and page.chart.series
        return bool(ok) and with_header(lambda: ranking(d, k, page))
    if variant == "metric":
        return bool(page.cols) and with_header(lambda: metric(d, k, page))
    if variant == "heat":
        return bool(page.headers) and with_header(lambda: heat_table(d, k, page))
    if variant == "grid":
        return bool(page.steps) and with_header(lambda: step_grid(d, k, page))
    if variant == "dashboard":
        return len(page.stats or []) >= 3 and with_header(lambda: dashboard(d, k, page))
    return False
