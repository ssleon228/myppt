"""排版引擎：deck 页面 → pptx。

从旧项目 api/pptx.ts 逐函数移植，坐标体系不变（设计稿 1920×1080 px，IN(px)=px/144 英寸）。
与旧版的差别：旧版用 SVG 栅格图片代替的东西（渐变、模板异形、裁剪图片、圆弧、金字塔/漏斗等）
这里全部写成原生 OOXML 形状（gradFill / prstGeom / custGeom），在 PowerPoint 里可编辑、放大不糊。
"""
import math
import os
import re

from .ooxml.geom import Path, parse_svg_path
from .ooxml.util import mix, js_round
from . import fontmetrics
from .themes import DEFAULT_THEME, asset_path


class AD(dict):
    """属性访问的 dict（C.primary 风格，缺键返回 None，与 TS 可选链一致）"""
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


def ad(v):
    """递归把 dict 转成 AD"""
    if isinstance(v, dict) and not isinstance(v, AD):
        return AD({k: ad(x) for k, x in v.items()})
    if isinstance(v, list):
        return [ad(x) for x in v]
    return v


# 设计系统坐标单位：1920×1080 px；@144PPI → 13.333×7.5 英寸
def IN(px):
    return px / 144.0


BODY_BOOST = 1.18


def FS(px):
    """字号换算：设计稿 px → pt；正文小字（≤30px）放大 18%"""
    return (px / 2.0) * (BODY_BOOST if px <= 30 else 1)


MIN_TEXT_PX = 21


def clamp_text_px(px):
    return max(MIN_TEXT_PX, js_round(px))


PAGE_W = 1920
PAGE_H = 1080
AREA = AD(x=72, y=200, w=1776, h=780)


def R(text, **o):
    """文字 run"""
    return {"text": "" if text is None else str(text), "options": o}


# ── 主题状态（render_deck 开始时由 apply_theme 设置；渲染是同步的） ──
class _K:
    pass


K = _K()
C = AD()


def apply_theme(theme=None, fonts=None):
    """设置当前主题。fonts={'cn':中文字体,'latin':西文字体,'hei':标题黑体}（缺省取模板配置）"""
    global C
    t = ad(theme or DEFAULT_THEME)
    C = AD(dict(t.colors or {}))
    C["white"] = "FFFFFF"
    K.theme = t
    fcfg = AD(dict(t.get("fonts") or {}))
    if fonts:
        fcfg.update({k: v for k, v in fonts.items() if v})
    K.FONT = fcfg.cn or t.font or "微软雅黑"
    K.FONT_HEI = fcfg.hei or t.fontHei or "黑体"
    K.LATIN = fcfg.latin or None
    K.STYLE = t.style or "generic"
    K.ACCENTS = [C.blue, C.primary, C.accent, C.green]
    K.CHART_COLORS = [C.blue, C.primary, C.green, C.accent, C.gray]
    K.TPL_ID = t.id
    K.A = t.assets or AD()
    K.show_footer = True
    K.base_dir = None
    K.warnings = []


apply_theme()


def tpl_asset(rel):
    return asset_path(K.theme, rel)


def text_em(s, font=None):
    """文本宽度（em）：本机字体真实字宽，缺字体回退估算"""
    return fontmetrics.text_em(s, font or K.FONT, K.LATIN)


def grad(from_, to, mid=None, ang=60):
    """主题单向渐变（与品牌位图 header_bar/bottom_bar 一致）：from 2% → mid 59% → to 100%"""
    if mid:
        stops = [{"pos": 2, "color": from_}, {"pos": 59, "color": mid}, {"pos": 100, "color": to}]
    else:
        stops = [{"pos": 0, "color": from_}, {"pos": 100, "color": to}]
    return {"type": "grad", "stops": stops, "ang": ang}


def card_shadow():
    return {"type": "outer", "color": "1A3A4A", "blur": 9, "offset": 3, "angle": 90, "opacity": 0.12}


NO_LINE = {"type": "none"}


# ── 模板装饰形状 / 图片（原生几何，不再栅格化） ──────────────────

_TEMPLATE_GEOMS = {
    "rect", "roundRect", "round1Rect", "round2SameRect", "snip1Rect", "snip2SameRect", "ellipse", "triangle",
    "rtTriangle", "diamond", "pentagon", "hexagon", "octagon", "parallelogram", "trapezoid", "chevron", "plus",
    "diagStripe", "donut", "pie", "blockArc", "star5",
}


def _shape_fill(f):
    f = f or AD(type="solid", color="FFFFFF")
    if f.type == "solid":
        return {"color": f.color}
    if f.type == "patt":
        return {"type": "patt", "prst": "wdUpDiag", "fg": f.fg, "bg": f.bg}
    if f.type == "grad":
        return {"type": "grad", "stops": [dict(s) for s in (f.stops or [])], "ang": f.ang or 0}
    return {"color": f.color or "FFFFFF"}


def add_template_shapes(slide, shapes):
    for s in shapes or []:
        o = dict(x=IN(s.x), y=IN(s.y), w=IN(s.w), h=IN(s.h), fill=_shape_fill(s.fill), line=NO_LINE,
                 rotate=s.rotation or None, flipH=bool(s.flipH), flipV=bool(s.flipV))
        if s.geom == "cust" and s.path:
            p = parse_svg_path(s.path)
            if not p.empty():
                slide.add_custom(p, local=(0, 0, max(1e-6, s.w), max(1e-6, s.h)), **o)
                continue
        geom = s.geom if s.geom in _TEMPLATE_GEOMS else "rect"
        if geom == "diagStripe":
            # 斜纹：45° 条纹图案（条纹色 = 填充色 / 渐变首色），底透明
            f = s.fill or AD()
            color = f.color if f.type == "solid" else (f.fg if f.type == "patt" else ((f.stops or [AD()])[0].color or "000000"))
            o["fill"] = {"type": "patt", "prst": "wdUpDiag", "fg": color, "bg": "FFFFFF", "bgAlpha": 0}
            geom = "rect"
        slide.add_shape(geom, **o)


def add_template_pic(slide, p):
    """模板提取图片：裁剪路径（custGeom）、旋转、翻转全部原生表达"""
    path = tpl_asset(p.path)
    if not path:
        K.warnings.append("模板图片缺失：%s" % p.path)
        return
    o = dict(x=IN(p.x), y=IN(p.y), w=IN(p.w), h=IN(p.h))
    if p.clip:
        cp = parse_svg_path(p.clip)
        if not cp.empty():
            from .ooxml.util import emu
            cx, cy = max(1, emu(o["w"])), max(1, emu(o["h"]))
            o["geom"] = cp.to_custgeom(cx / max(1e-6, p.w), cy / max(1e-6, p.h), cx, cy)
    if p.rotation and (p.clip or p.rotWithShape is not False):
        o["rotate"] = p.rotation
    if p.rotWithShape is False and p.clip:
        o["rotWithShape"] = False
    if p.flipH:
        o["flipH"] = True
    if p.flipV:
        o["flipV"] = True
    slide.add_image(path=path, **o)


def add_bg_image(slide, rel):
    path = tpl_asset(rel)
    if path:
        slide.add_image(path=path, x=0, y=0, w=IN(PAGE_W), h=IN(PAGE_H))


# ── 页眉 / 页脚 ──────────────────────────────────────────────

def header_font_size(title):
    n = len(str(title or ""))
    if n <= 22:
        return 56, 2.5
    if n <= 30:
        return 44, 1
    return 38, 0.5


def _header_title(slide, title, box=None, min_w=None):
    ht = box or AD()
    fs, cs = header_font_size(title)
    w = ht.w if ht.w is not None else 1700
    if min_w:
        w = max(ht.w or 0, min_w)
    slide.add_text(title, x=IN(41.4 if ht.x is None else ht.x), y=IN(38.4 if ht.y is None else ht.y), w=IN(w),
                   h=IN(max(ht.h or 68, 68) if min_w else (ht.h or 68)), fontSize=FS(fs), bold=True,
                   color=ht.color or C.white, fontFace=K.FONT, charSpacing=cs, align="left", valign="middle",
                   name="Title")


def add_generic_header(slide, title):
    A = K.A
    if A.contentBg:
        add_bg_image(slide, A.contentBg)
        _header_title(slide, title, A.headerTitle, min_w=1500)
        return
    if A.headerShapes:
        add_template_shapes(slide, A.headerShapes)
        for p in A.headerPics or []:
            add_template_pic(slide, p)
        _header_title(slide, title, A.headerTitle)
        return
    slide.add_shape("rect", x=0, y=0, w=IN(PAGE_W), h=IN(144.9), fill=grad(C.primary, C.blue, C.mid), line=NO_LINE)
    _header_title(slide, title)


def add_header(slide, title):
    add_generic_header(slide, title)


def add_footer(slide, note, page_no):
    if not K.show_footer:
        return
    if note:
        slide.add_text(note, x=IN(41), y=IN(1020), w=IN(1600), h=IN(34), fontSize=FS(20), color=C.gray,
                       fontFace=K.FONT, align="left", valign="middle")
    slide.add_text(str(page_no), x=IN(1780), y=IN(1020), w=IN(100), h=IN(34), fontSize=FS(20), color=C.gray,
                   fontFace=K.FONT, align="right", valign="middle", wrap=False)


# ── 封面 ─────────────────────────────────────────────────────

def _lum(hexs):
    r, g, b = (int(hexs[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def cover_text_fallback():
    bg = 1
    best = 0
    for s in K.A.coverShapes or []:
        area = s.w * s.h
        if area <= best or area < 1920 * 1080 * 0.5:
            continue
        best = area
        f = s.fill or AD()
        hx = f.color if f.type == "solid" else (f.bg if f.type == "patt" else ((f.stops or [AD()])[0].color))
        if hx:
            bg = _lum(hx)
    return "FFFFFF" if bg < 0.45 else C.deep


def add_cover(slide, page):
    A = K.A
    if K.STYLE == "generic":
        pics = A.cover
        if A.coverBg or pics:
            slide.background = "FFFFFF"
            if A.coverBg:
                add_bg_image(slide, A.coverBg)
            else:
                add_template_shapes(slide, A.coverShapes)
                for p in pics or []:
                    add_template_pic(slide, p)
            tb = A.coverTitle or AD(x=150, y=400, w=900, h=260, color="FFFFFF")
            t_color = tb.color or cover_text_fallback()
            slots = A.coverTexts or []
            has_roles = any(s.role for s in slots)
            presenter = next((s for s in slots if s.role == "presenter"), None) or \
                next((s for s in slots if "汇报" in (s.text or "")), None)
            if has_roles:
                subtitle_slot = next((s for s in slots if s.role == "subtitle"), None)
                decor = [s for s in slots if s is not presenter and s is not subtitle_slot and s.role != "logo"]
            else:
                subtitle_slot = next((s for s in slots if s is not presenter and s.y + s.h <= tb.y + 40), None)
                decor = []
            title_pt = min(tb.sz / 100.0, 88) if tb.sz else FS(60)
            em = text_em(page.title)
            fit_pt = (tb.w / em / 2) * 0.88 if em > 0 else title_pt
            final_pt = max(28, min(title_pt, math.floor(fit_pt)))
            box_h = max(tb.h, 260)
            runs = [R(page.title, fontSize=final_pt, bold=True, fontFace=K.FONT_HEI, breakLine=True)]
            if page.subtitle and not subtitle_slot:
                runs.append(R(page.subtitle, fontSize=FS(28), fontFace=K.FONT, breakLine=True))
            if page.meta and not presenter:
                runs.append(R(page.meta, fontSize=FS(20), fontFace=K.FONT, transparency=15))
            slide.add_text(runs, x=IN(tb.x), y=IN(tb.y), w=IN(tb.w), h=IN(box_h), color=t_color, align="left",
                           valign="middle", lineSpacingMultiple=1.3, name="Title")
            sub_text = page.subtitle or (subtitle_slot.text if has_roles and subtitle_slot else None)
            if subtitle_slot and sub_text:
                slide.add_text(sub_text, x=IN(subtitle_slot.x), y=IN(subtitle_slot.y), w=IN(subtitle_slot.w),
                               h=IN(max(subtitle_slot.h, 60)), color=subtitle_slot.color or t_color,
                               fontSize=subtitle_slot.sz / 100.0 if subtitle_slot.sz else FS(24), fontFace=K.FONT,
                               charSpacing=2, align="left", valign="middle")
            meta_text = page.meta or (presenter.text if has_roles and presenter else None)
            if presenter and meta_text:
                slide.add_text(meta_text, x=IN(presenter.x), y=IN(presenter.y), w=IN(presenter.w),
                               h=IN(max(presenter.h, 44)), color=presenter.color or t_color,
                               fontSize=presenter.sz / 100.0 if presenter.sz else FS(20), fontFace=K.FONT,
                               align="center", valign="middle")
            for s in decor:
                if not s.text:
                    continue
                slide.add_text(s.text, x=IN(s.x), y=IN(s.y), w=IN(s.w), h=IN(max(s.h, 40)), color=s.color or t_color,
                               fontSize=s.sz / 100.0 if s.sz else FS(20), fontFace=K.FONT,
                               charSpacing=2 if s.role == "eyebrow" else 0, align="left", valign="middle")
            return
        slide.add_shape("rect", x=0, y=0, w=IN(PAGE_W), h=IN(PAGE_H), fill=grad(C.primary, C.blue, C.mid), line=NO_LINE)
        slide.add_text(page.title, x=IN(160), y=IN(400), w=IN(1600), h=IN(120), fontSize=FS(60), bold=True,
                       color=C.white, fontFace=K.FONT_HEI, align="center", valign="middle", name="Title")
        if page.subtitle:
            slide.add_text(page.subtitle, x=IN(160), y=IN(540), w=IN(1600), h=IN(48), fontSize=FS(28), color=C.white,
                           fontFace=K.FONT, align="center", valign="middle")
        if page.meta:
            slide.add_text(page.meta, x=IN(160), y=IN(620), w=IN(1600), h=IN(36), fontSize=FS(20), color=C.white,
                           fontFace=K.FONT, align="center", valign="middle", transparency=20)
        return


# ── 章节页 ───────────────────────────────────────────────────

def fit_chapter_title_pt(title, box_w, box_h, base_pt, part_lines=0):
    em = max(1, text_em(title, K.FONT))

    def fit(lines):
        return min((box_w * 0.94) / (2 * em * lines), (box_h * 0.94) / (2 * 1.25 * (part_lines + lines)), base_pt)

    one = fit(1)
    if one >= 28:
        return one
    return max(20, max(one, fit(2)))


def _part_text(page):
    return page.partText if page.partText is not None else "PART %s" % ("" if page.part is None else page.part)


def add_chapter(slide, page):
    A = K.A
    if K.STYLE == "generic":
        if A.chapterBg:
            add_bg_image(slide, A.chapterBg)
            tb = A.chapterTitle or AD()
            pb = A.chapterPart
            if pb:
                slide.add_text(_part_text(page), x=IN(pb.x), y=IN(pb.y), w=IN(pb.w), h=IN(max(pb.h, 40)),
                               fontSize=pb.sz / 100.0 if pb.sz else FS(32), bold=True, color=pb.color or "FFFFFF",
                               fontFace=K.FONT, align="center" if pb.w > PAGE_W * 0.6 else "left", valign="middle")
            bw = tb.w if tb.w is not None else 1600
            bh = max(tb.h if tb.h is not None else 160, 80)
            slide.add_text(page.title, x=IN(160 if tb.x is None else tb.x), y=IN(420 if tb.y is None else tb.y),
                           w=IN(bw), h=IN(bh),
                           fontSize=fit_chapter_title_pt(str(page.title or ""), bw, bh,
                                                         min(tb.sz / 100.0, 72) if tb.sz else FS(72)),
                           bold=True, color=tb.color or "FFFFFF", fontFace=K.FONT_HEI,
                           align="center" if (tb.w or 0) > PAGE_W * 0.6 else "left", valign="middle", name="Title")
            return
        slide.background = "FFFFFF"

        def blend_w(h):
            a = 216 / 255.0
            return "".join("%02X" % js_round(int(h[i:i + 2], 16) * a + 255 * (1 - a)) for i in (0, 2, 4))

        slide.add_shape("rect", x=IN(11.7), y=IN(9.5), w=IN(1896.6), h=IN(858.1),
                        fill={"type": "grad", "ang": 60, "stops": [
                            {"pos": 2, "color": blend_w(C.primary)}, {"pos": 59, "color": blend_w(C.mid or C.primary)},
                            {"pos": 100, "color": blend_w(C.blue)}]}, line=NO_LINE)
        slide.add_text([R(_part_text(page), breakLine=True), R(page.title)], x=0, y=IN(351.3), w=IN(PAGE_W), h=IN(180),
                       fontSize=fit_chapter_title_pt(str(page.title or ""), PAGE_W, 180, FS(72), 1), bold=True,
                       color=C.white, fontFace=K.FONT, align="center", valign="middle", lineSpacingMultiple=1.25,
                       name="Title")
        slide.add_shape("rect", x=0, y=IN(1000.5), w=IN(1815.2), h=IN(59.8), fill=grad(C.primary, C.blue, C.mid),
                        line=NO_LINE)
        cp = A.chapterPics
        if cp:
            for p in cp:
                add_template_pic(slide, p)
        else:
            # 无章节图片：用页眉里的品牌标（如有），否则主题色块
            hp = [p for p in (A.headerPics or []) if p.w < 200 and p.h < 200]
            if hp:
                p = AD(dict(hp[0]))
                p.update(x=1840.5, y=999, w=60.5, h=62.8 * (hp[0].h / float(hp[0].w)) * (60.5 / 62.8))
                slide.add_shape("rect", x=IN(1832), y=IN(994), w=IN(78), h=IN(72), fill={"color": C.primary}, line=NO_LINE)
                add_template_pic(slide, p)
            else:
                slide.add_shape("rect", x=IN(1840.5), y=IN(999), w=IN(60.5), h=IN(62.8), fill={"color": C.primary},
                                line=NO_LINE)
        return


# ── 通用小工具 ───────────────────────────────────────────────

def fit_big_number(text, box_w, base):
    t = str(text if text is not None else "")
    em = text_em(t, K.FONT)
    if not em:
        return base
    fs = math.floor((box_w * 0.5 * 0.92) / em)
    return max(28, min(base, fs))


def item_text_of(it):
    if isinstance(it, str):
        return it
    if isinstance(it, dict):
        return "：".join(str(v) for v in (it.get("text"), it.get("title"), it.get("desc")) if v)
    return ""


def coerce_to_bullets(page):
    texts = []
    for key in ("bullets", "items", "steps", "points"):
        arr = page.get(key)
        if not isinstance(arr, list):
            continue
        for it in arr:
            if isinstance(it, str):
                texts.append(it)
            elif isinstance(it, dict):
                line = "：".join(str(v) for v in (it.get("title"), it.get("text"), it.get("desc")) if v)
                if line:
                    texts.append(line)
        if texts:
            break
    if not texts:
        texts.append(page.title or "要点")
    out = AD(dict(page))
    out.type = "bullets"
    out["items"] = [AD(text=t[:80]) for t in texts[:6]]
    out.groups = None
    return out


def _bullet_runs(items, color, gap_px=12, item_color=None):
    runs = []
    n = len(items)
    for i, it in enumerate(items):
        runs.append(R("●  ", color=color, bold=True))
        runs.append(R(item_text_of(it) if not isinstance(it, str) else it, color=item_color or C.text, breakLine=True))
        if i < n - 1:
            runs.append(R(" ", fontSize=FS(gap_px), breakLine=True))
    return runs


def has_takeaways(page):
    return any(str(t or "").strip() for t in (page.takeaways or []))


# ── 内容页：要点 / 大数字 / 结论条 / 对比 / 表格 / 步骤 / 矩阵 / 时间轴 / 金句 / 目录 / 封底 ──

def add_takeaways_bar(slide, page, y=870):
    tks = [t for t in (page.takeaways or []) if str(t or "").strip()][:2]
    if not tks:
        return
    slide.add_shape("roundRect", x=IN(72), y=IN(y), w=IN(1776), h=IN(110), fill={"color": C.soft},
                    line={"color": C.line, "width": 1}, rectRadius=IN(8))
    slide.add_shape("rect", x=IN(72), y=IN(y), w=IN(8), h=IN(110), fill={"color": C.primary}, line=NO_LINE)
    runs = []
    for i, t in enumerate(tks):
        runs.append(R("%s  " % ("结论" if i == 0 else "▪"), color=C.deep, bold=True, breakLine=False))
        runs.append(R(t, color=C.text, breakLine=i < len(tks) - 1))
    slide.add_text(runs, x=IN(104), y=IN(y), w=IN(1712), h=IN(110), fontSize=FS(27), fontFace=K.FONT, align="left",
                   valign="middle", lineSpacingMultiple=1.35)


def add_bullets(slide, page):
    area_h = 654 if has_takeaways(page) else AREA.h
    if page.groups:
        groups = page.groups[:4]
        cols = len(groups) if len(groups) <= 2 else 2
        rows = int(math.ceil(len(groups) / float(cols)))
        gap = 32
        cw = (AREA.w - (cols - 1) * gap) / cols
        ch = (area_h - (rows - 1) * gap) / rows
        for gi, g in enumerate(groups):
            cx = AREA.x + (gi % cols) * (cw + gap)
            cy = AREA.y + (gi // cols) * (ch + gap)
            accent = K.ACCENTS[gi % len(K.ACCENTS)]
            slide.add_shape("roundRect", x=IN(cx), y=IN(cy), w=IN(cw), h=IN(ch), fill={"color": C.white},
                            line={"color": C.line, "width": 1}, rectRadius=IN(10), shadow=card_shadow())
            if g.icon is not None or K.icons_on:
                icon_badge(slide, g.icon, g.heading, cx + 34, cy + 30, 44, accent)
                hx = cx + 92
            else:
                slide.add_shape("roundRect", x=IN(cx + 40), y=IN(cy + 42), w=IN(20), h=IN(20), fill={"color": accent},
                                line=NO_LINE, rectRadius=IN(4))
                hx = cx + 76
            slide.add_text(g.heading, x=IN(hx), y=IN(cy + 28), w=IN(cw - (hx - cx) - 40), h=IN(48), fontSize=FS(30),
                           bold=True, color=C.deep, fontFace=K.FONT, align="left", valign="middle")
            slide.add_text(_bullet_runs(g.get("items") or [], accent, 10), x=IN(cx + 42), y=IN(cy + 96),
                           w=IN(cw - 84), h=IN(ch - 128), fontSize=FS(23), fontFace=K.FONT, align="left", valign="top",
                           lineSpacingMultiple=1.4)
        add_takeaways_bar(slide, page)
        return
    items = (page.get("items") or [])[:6]
    if not items:
        return
    n = len(items)
    gap = 22
    ch = min(140, (area_h - (n - 1) * gap) / n)
    total = n * ch + (n - 1) * gap
    start_y = AREA.y + (area_h - total) / 2
    for i, item in enumerate(items):
        cy = start_y + i * (ch + gap)
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("roundRect", x=IN(AREA.x), y=IN(cy), w=IN(AREA.w), h=IN(ch), fill={"color": C.soft},
                        line=NO_LINE, rectRadius=IN(10))
        slide.add_text(str(i + 1).zfill(2), shape="ellipse", x=IN(AREA.x + 32), y=IN(cy + ch / 2 - 31), w=IN(62),
                       h=IN(62), fill={"color": accent}, line=NO_LINE, fontSize=FS(22), bold=True, color=C.white,
                       fontFace=K.FONT, align="center", valign="middle", margin=0, wrap=False)
        slide.add_text(item_text_of(item), x=IN(AREA.x + 126), y=IN(cy + 10), w=IN(AREA.w - 176), h=IN(ch - 20),
                       fontSize=FS(26), color=C.text, fontFace=K.FONT, align="left", valign="middle",
                       lineSpacingMultiple=1.3)
    add_takeaways_bar(slide, page)


def add_stats(slide, page):
    stats = (page.stats or [])[:4]
    if not stats:
        return
    cols = 1 if len(stats) == 1 else 2
    rows = int(math.ceil(len(stats) / float(cols)))
    gap = 32
    cw = (AREA.w - (cols - 1) * gap) / cols
    ch = (AREA.h - (rows - 1) * gap) / rows
    for i, s in enumerate(stats):
        cx = AREA.x + (i % cols) * (cw + gap)
        cy = AREA.y + (i // cols) * (ch + gap)
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("roundRect", x=IN(cx), y=IN(cy), w=IN(cw), h=IN(ch), fill={"color": C.soft}, line=NO_LINE,
                        rectRadius=IN(12), shadow=card_shadow())
        vw = cw - 96
        if s.icon is not None or K.icons_on:
            if icon_badge(slide, s.icon, s.label, cx + cw - 52 - 84, cy + (90 if rows == 1 else 44), 84, accent) \
                    is not False:
                vw = cw - 96 - 84 - 16  # 大数字让出右上角图标位，避免压字
        slide.add_shape("roundRect", x=IN(cx + 52), y=IN(cy + (90 if rows == 1 else 52)), w=IN(72), h=IN(10),
                        fill={"color": accent}, line=NO_LINE, rectRadius=IN(5))
        slide.add_text(s.value, x=IN(cx + 48), y=IN(cy + (120 if rows == 1 else 84)), w=IN(vw), h=IN(130),
                       fontSize=fit_big_number(s.value, vw, 110 if rows == 1 else 88), bold=True, color=accent,
                       fontFace=K.FONT, align="left", valign="middle", wrap=False)
        slide.add_text(s.label, x=IN(cx + 52), y=IN(cy + ch - (160 if rows == 1 else 118)), w=IN(cw - 104),
                       h=IN(110 if rows == 1 else 84), fontSize=FS(26), color=C.text, fontFace=K.FONT, align="left",
                       valign="top", lineSpacingMultiple=1.3)


def _top_round_bar(slide, x, y, w, h, color, r=10):
    """上圆下方的标题栏：roundRect + 底部同色矩形补角"""
    slide.add_shape("roundRect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": color}, line=NO_LINE, rectRadius=IN(r))
    slide.add_shape("rect", x=IN(x), y=IN(y + h - 14), w=IN(w), h=IN(14), fill={"color": color}, line=NO_LINE)


def add_compare(slide, page):
    top = 190
    height = 660 if has_takeaways(page) else 790
    for side, x, color in ((page.left, 72, C.blue), (page.right, 990, C.primary)):
        if not side:
            continue
        slide.add_shape("roundRect", x=IN(x), y=IN(top), w=IN(858), h=IN(height), fill={"color": C.white},
                        line={"color": C.line, "width": 1}, rectRadius=IN(10), shadow=card_shadow())
        _top_round_bar(slide, x, top, 858, 96, color)
        name = [R(side.name, fontSize=FS(32), breakLine=True), R(side.nameEn, fontSize=FS(18), transparency=25)] \
            if side.nameEn else side.name
        slide.add_text(name, x=IN(x), y=IN(top), w=IN(858), h=IN(96), bold=True, color=C.white, fontFace=K.FONT,
                       align="center", valign="middle", lineSpacingMultiple=1.15)
        slide.add_text(_bullet_runs(side.points or [], color, 12), x=IN(x + 44), y=IN(top + 128), w=IN(858 - 88),
                       h=IN(height - 168), fontSize=FS(24), fontFace=K.FONT, align="left", valign="top",
                       lineSpacingMultiple=1.6)
    if page.left and page.right:
        slide.add_text("VS", shape="ellipse", x=IN(900), y=IN(top + height / 2 - 60), w=IN(120), h=IN(120),
                       fill={"color": C.deep}, line={"color": C.white, "width": 3}, fontSize=FS(44), bold=True,
                       color=C.white, fontFace=K.FONT, align="center", valign="middle", shadow=card_shadow())
    add_takeaways_bar(slide, page)


def add_table_page(slide, page):
    headers = page.headers or []
    all_rows = page.rows or []
    if not headers:
        return
    rows = all_rows[:8]
    hidden = len(all_rows) - len(rows)
    header_row = [{"text": h, "options": {"fill": {"color": C.deep}, "color": C.white, "bold": True,
                                          "fontSize": FS(26)}} for h in headers]
    body = []
    for ri, r in enumerate(rows):
        body.append([{"text": (r[ci] if ci < len(r) and r[ci] is not None else ""),
                      "options": {"fill": {"color": C.white if ri % 2 == 0 else C.soft},
                                  "color": C.deep if ci == 0 else C.text, "bold": ci == 0, "fontSize": FS(22)}}
                     for ci in range(len(headers))])
    hint = [{"text": ("仅显示前 %d 项（共 %d 项）" % (len(rows), len(all_rows))) if ci == 0 and hidden > 0 else "",
             "options": {"fill": {"color": C.soft}, "color": C.gray, "fontSize": FS(18)}} for ci in range(len(headers))]
    row_hs = [IN(88)] + [IN(78)] * len(rows) + ([IN(50)] if hidden > 0 else [])
    col_w = IN(1776) / len(headers)
    slide.add_table([header_row] + body + ([hint] if hidden > 0 else []), x=IN(72), y=IN(210), w=IN(1776),
                    colW=[col_w] * len(headers), rowH=row_hs, fontFace=K.FONT, align="center", valign="middle",
                    border={"pt": 1, "color": C.line})
    if len(rows) <= 7:
        add_takeaways_bar(slide, page)


def add_steps(slide, page):
    steps = (page.steps or [])[:5]
    if not steps:
        return
    n = len(steps)
    gap = 40
    cw = (AREA.w - (n - 1) * gap) / n
    badge = 76
    card_y = 440
    card_h = 300
    first = AREA.x + cw / 2
    last = AREA.x + (n - 1) * (cw + gap) + cw / 2
    slide.add_shape("line", x=IN(first), y=IN(card_y), w=IN(last - first), h=0, line={"color": C.line, "width": 3})
    for i, st in enumerate(steps):
        cx = AREA.x + i * (cw + gap)
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("roundRect", x=IN(cx), y=IN(card_y), w=IN(cw), h=IN(card_h), fill={"color": C.white},
                        line={"color": C.line, "width": 1}, rectRadius=IN(10), shadow=card_shadow())
        slide.add_text(str(i + 1), shape="ellipse", x=IN(cx + cw / 2 - badge / 2), y=IN(card_y - badge / 2),
                       w=IN(badge), h=IN(badge), fill={"color": accent}, line={"color": C.white, "width": 3},
                       fontSize=FS(30), bold=True, color=C.white, fontFace=K.FONT, align="center", valign="middle",
                       margin=0, wrap=False)
        if st.icon is not None or K.icons_on:
            # 步骤图标：卡片上方居中（徽章之上）
            icon_badge(slide, st.icon, st.title, cx + cw / 2 - 40, card_y - badge / 2 - 120, 80, accent, style="soft")
        slide.add_text(st.title, x=IN(cx + 24), y=IN(card_y + badge / 2 + 24), w=IN(cw - 48), h=IN(56),
                       fontSize=FS(30), bold=True, color=C.deep, fontFace=K.FONT, align="center", valign="middle")
        if st.desc:
            slide.add_text(st.desc, x=IN(cx + 28), y=IN(card_y + badge / 2 + 96), w=IN(cw - 56),
                           h=IN(card_h - badge / 2 - 136), fontSize=FS(22), color=C.text, fontFace=K.FONT,
                           align="center", valign="top", lineSpacingMultiple=1.45)


def add_matrix(slide, page):
    quads = (page.quadrants or [])[:4]
    if not quads:
        return
    grid_y, grid_h, gap = 230, 700, 24
    cw = (AREA.w - gap) / 2
    ch = (grid_h - gap) / 2
    for i, q in enumerate(quads):
        cx = AREA.x + (i % 2) * (cw + gap)
        cy = grid_y + (i // 2) * (ch + gap)
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("roundRect", x=IN(cx), y=IN(cy), w=IN(cw), h=IN(ch), fill={"color": C.white},
                        line={"color": C.line, "width": 1}, rectRadius=IN(10), shadow=card_shadow())
        _top_round_bar(slide, cx, cy, cw, 72, accent)
        slide.add_text(q.name, x=IN(cx), y=IN(cy), w=IN(cw), h=IN(72), fontSize=FS(28), bold=True, color=C.white,
                       fontFace=K.FONT, align="center", valign="middle")
        slide.add_text(_bullet_runs(q.get("items") or [], accent, 12), x=IN(cx + 40), y=IN(cy + 96), w=IN(cw - 80),
                       h=IN(ch - 128), fontSize=FS(24), fontFace=K.FONT, align="left", valign="top",
                       lineSpacingMultiple=1.5)
    if page.yLabel:
        slide.add_text(page.yLabel, x=IN(AREA.x), y=IN(182), w=IN(600), h=IN(36), fontSize=FS(20), color=C.gray,
                       fontFace=K.FONT, align="left", valign="middle")
    if page.xLabel:
        slide.add_text(page.xLabel, x=IN(AREA.x + AREA.w - 600), y=IN(944), w=IN(600), h=IN(36), fontSize=FS(20),
                       color=C.gray, fontFace=K.FONT, align="right", valign="middle")


def add_timeline(slide, page):
    nodes = (page.timeline or [])[:6]
    if not nodes:
        return
    n = len(nodes)
    line_x, top_y, bottom_y = 400, 280, 900
    step = (bottom_y - top_y) / (n - 1) if n > 1 else 0
    slide.add_shape("line", x=IN(line_x), y=IN(top_y), w=0, h=IN(bottom_y - top_y), line={"color": C.line, "width": 3})
    for i, nd in enumerate(nodes):
        ny = top_y + i * step if n > 1 else (top_y + bottom_y) / 2
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("ellipse", x=IN(line_x - 15), y=IN(ny - 15), w=IN(30), h=IN(30), fill={"color": accent},
                        line={"color": C.white, "width": 3})
        slide.add_text(nd.label, shape="roundRect", x=IN(110), y=IN(ny - 30), w=IN(230), h=IN(60),
                       fill={"color": accent}, line=NO_LINE, rectRadius=IN(30), fontSize=FS(24), bold=True,
                       color=C.white, fontFace=K.FONT, align="center", valign="middle", margin=0, wrap=False)
        slide.add_text(nd.title, x=IN(460), y=IN(ny - 34), w=IN(1330), h=IN(48), fontSize=FS(30), bold=True,
                       color=C.deep, fontFace=K.FONT, align="left", valign="middle")
        if nd.desc:
            slide.add_text(nd.desc, x=IN(460), y=IN(ny + 16), w=IN(1330), h=IN(64), fontSize=FS(22), color=C.gray,
                           fontFace=K.FONT, align="left", valign="top", lineSpacingMultiple=1.35)


def add_quote(slide, page):
    quote = str(page.quote or "").strip()
    if not quote:
        return
    slide.add_text("“", x=IN(200), y=IN(220), w=IN(360), h=IN(280), fontSize=FS(220), bold=True, color=C.line,
                   fontFace=K.FONT_HEI, align="left", valign="top")
    slide.add_text(quote, x=IN(280), y=IN(400), w=IN(1360), h=IN(260), fontSize=FS(48), bold=True, color=C.deep,
                   fontFace=K.FONT, align="center", valign="middle", lineSpacingMultiple=1.5)
    slide.add_shape("roundRect", x=IN(880), y=IN(716), w=IN(160), h=IN(10), fill={"color": C.primary}, line=NO_LINE,
                    rectRadius=IN(5))
    if page.subtitle:
        slide.add_text("—— %s" % page.subtitle, x=IN(560), y=IN(760), w=IN(800), h=IN(48), fontSize=FS(24),
                       color=C.gray, fontFace=K.FONT, align="center", valign="middle")
    if K.STYLE == "generic" and K.A.decor:
        d = sorted(K.A.decor, key=lambda a: -a.w * a.h)[0]
        ratio = d.h / float(d.w)
        w = min(160, d.w)
        h = w * ratio
        if h > 160:
            h = 160
            w = h / ratio
        p = tpl_asset(d.path)
        if p:
            slide.add_image(path=p, x=IN(1840 - w), y=IN(1010 - h), w=IN(w), h=IN(h))


_COLON = re.compile(r"[：:]")


def add_toc(slide, page):
    items = (page.get("items") or [])[:8]
    if not items:
        return
    top = 145
    slide.add_shape("rect", x=0, y=IN(top), w=IN(560), h=IN(1080 - top), fill={"color": C.primary}, line=NO_LINE)
    slide.add_shape("rect", x=IN(560), y=IN(top), w=IN(14), h=IN(1080 - top), fill={"color": C.blue or C.deep},
                    line=NO_LINE)
    slide.add_text("CONTENTS", x=IN(90), y=IN(470), w=IN(440), h=IN(90), fontSize=FS(64), bold=True, color=C.white,
                   fontFace=K.FONT, charSpacing=4, margin=0)
    slide.add_shape("rect", x=IN(94), y=IN(580), w=IN(80), h=IN(6), fill={"color": C.white}, line=NO_LINE)
    slide.add_text("共 %d 个部分" % len(items), x=IN(90), y=IN(606), w=IN(440), h=IN(50), fontSize=FS(28),
                   color=C.white, fontFace=K.FONT, margin=0)
    two = len(items) > 6
    per = int(math.ceil(len(items) / 2.0)) if two else len(items)
    area_x = 700
    area_w = 1920 - area_x - 110
    col_w = (area_w - 60) / 2.0 if two else area_w
    head_px = 34 if two else 44
    row_h = min(170, 800.0 / per)
    start_y = top + (1080 - top - per * row_h) / 2
    for i, it in enumerate(items):
        col = i // per if two else 0
        row = i % per if two else i
        x = area_x + col * (col_w + 60)
        y = start_y + row * row_h
        full = item_text_of(it).strip()
        m = _COLON.search(full)
        cut = m.start() if m else -1
        head = full[:cut] if 0 < cut < len(full) - 1 else full
        desc = full[cut + 1:].strip() if 0 < cut < len(full) - 1 else ""
        num_w = 110 if two else min(170, row_h * 1.15)
        slide.add_text(str(i + 1).zfill(2), x=IN(x), y=IN(y), w=IN(num_w), h=IN(row_h),
                       fontSize=FS(60 if two else min(80, row_h * 0.56)), bold=True, color=C.primary,
                       fontFace=K.FONT, valign="middle", margin=0)
        tx = x + num_w + 20
        tw = col_w - num_w - 20
        if desc:
            slide.add_text([R(head, fontSize=FS(min(head_px, row_h * 0.3)), bold=True, color=C.deep, breakLine=True),
                            R(desc, fontSize=FS(min(26, row_h * 0.18)), color=C.gray)],
                           x=IN(tx), y=IN(y), w=IN(tw), h=IN(row_h), fontFace=K.FONT, valign="middle", margin=0,
                           paraSpaceAfter=4)
        else:
            slide.add_text(head, x=IN(tx), y=IN(y), w=IN(tw), h=IN(row_h), fontSize=FS(min(head_px, row_h * 0.3)),
                           bold=True, color=C.deep, fontFace=K.FONT, valign="middle", margin=0, fit="shrink")
        if row < per - 1 and i < len(items) - 1:
            slide.add_shape("line", x=IN(x), y=IN(y + row_h), w=IN(col_w), h=0, line={"color": C.line, "width": 1})


def _end_runs(page):
    return [R(page.subtitle if page.subtitle is not None else "THANK YOU", fontSize=FS(80), bold=True),
            R("  %s" % (page.title or "谢谢"), fontSize=FS(66), bold=True, charSpacing=3.4)]


def add_end(slide, page):
    A = K.A
    if K.STYLE == "generic":
        if A.endBg or A.end or A.endShapes:
            slide.background = "FFFFFF"
            if A.endBg:
                add_bg_image(slide, A.endBg)
            else:
                add_template_shapes(slide, A.endShapes)
                for p in A.end or []:
                    add_template_pic(slide, p)
            tb = A.endTitle or AD(x=0, y=400, w=PAGE_W, h=200, color="FFFFFF")
            if A.endBg and tb.w < PAGE_W * 0.5:
                tb = AD(dict(tb, x=0, w=PAGE_W, color="FFFFFF"))
            slide.add_text(_end_runs(page), x=IN(tb.x), y=IN(tb.y), w=IN(tb.w), h=IN(tb.h), color=tb.color or C.white,
                           fontFace=K.FONT, align="center", valign="middle", name="Title")
            return
        slide.add_shape("rect", x=0, y=0, w=IN(PAGE_W), h=IN(PAGE_H), fill=grad(C.primary, C.blue, C.mid), line=NO_LINE)
        slide.add_text(_end_runs(page), x=0, y=IN(460), w=IN(1920), h=IN(123), color=C.white, fontFace=K.FONT,
                       align="center", valign="middle", name="Title")
        return


# ── 甘特 / KPI / 组织树 / 同心圆 / 对比矩阵 / 问答 ──────────────

def add_gantt(slide, page):
    g = page.gantt
    tasks = ((g or AD()).tasks or [])[:8]
    if not g or not tasks:
        return
    seen = []
    for t in tasks:
        for k in (t.start, t.end):
            k = str(k if k is not None else "")
            if k not in seen:
                seen.append(k)

    def key_of(s):
        m = re.search(r"\d+", s)
        return float(m.group(0)) if m else 999 + seen.index(s)

    labels = sorted(seen, key=key_of)

    def idx_of(s):
        s = str(s if s is not None else "")
        return labels.index(s) if s in labels else 0

    nl = len(labels)
    name_w = 300
    grid_x = AREA.x + name_w + 28
    grid_w = AREA.w - name_w - 28
    col_w = grid_w / nl
    head_y, rows_y = 240, 306
    row_h = min(84, 620.0 / len(tasks))
    bottom = rows_y + len(tasks) * row_h
    for i, lb in enumerate(labels):
        slide.add_text(lb, x=IN(grid_x + i * col_w), y=IN(head_y), w=IN(col_w), h=IN(50), fontSize=FS(20), bold=True,
                       color=C.gray, fontFace=K.FONT, align="center", valign="middle")
        slide.add_shape("line", x=IN(grid_x + i * col_w), y=IN(head_y + 54), w=0, h=IN(bottom - head_y - 54),
                        line={"color": C.line, "width": 1})
    slide.add_shape("line", x=IN(grid_x + nl * col_w), y=IN(head_y + 54), w=0, h=IN(bottom - head_y - 54),
                    line={"color": C.line, "width": 1})
    if g.unit:
        slide.add_text("单位：%s" % g.unit, x=IN(grid_x + grid_w - 260), y=IN(head_y - 44), w=IN(260), h=IN(40),
                       fontSize=FS(18), color=C.gray, fontFace=K.FONT, align="right", valign="middle")
    for i, t in enumerate(tasks):
        ry = rows_y + i * row_h
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_text(t.task, x=IN(AREA.x), y=IN(ry), w=IN(name_w), h=IN(row_h), fontSize=FS(21), color=C.deep,
                       fontFace=K.FONT, align="right", valign="middle")
        si = idx_of(t.start)
        ei = max(si, idx_of(t.end))
        slide.add_shape("roundRect", x=IN(grid_x + si * col_w + 6), y=IN(ry + row_h * 0.24),
                        w=IN((ei - si + 1) * col_w - 12), h=IN(row_h * 0.52), fill={"color": accent}, line=NO_LINE,
                        rectRadius=IN(8))


def ring_segment(cx, cy, r_out, r_in, a0, a1):
    """圆环扇段路径（角度：度，0=正东，顺时针）"""
    p = Path()
    p.arc(cx, cy, r_out, r_out, a0, a1, connect=False)
    p.arc(cx, cy, r_in, r_in, a1, a0, connect=True)
    return p.close()


def add_ring_segment(slide, cx, cy, r_out, r_in, a0, a1, color):
    """在页面坐标（px）画圆环扇段；局部坐标框取整圆外接框，保证弧几何精确"""
    p = ring_segment(r_out, r_out, r_out, r_in, a0, a1)
    x0, y0, x1, y1 = p.bbox()
    slide.add_custom(p, local=(x0, y0, max(1e-6, x1 - x0), max(1e-6, y1 - y0)), x=IN(cx - r_out + x0),
                     y=IN(cy - r_out + y0), w=IN(x1 - x0), h=IN(y1 - y0), fill={"color": color}, line=NO_LINE)


def add_kpi(slide, page):
    gauges = (page.gauges or [])[:4]
    if not gauges:
        return
    n = len(gauges)
    zone_w = AREA.w / float(n)
    gcy = 640
    Ro, ri = 160, 120
    for i, gt in enumerate(gauges):
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        gcx = AREA.x + zone_w * (i + 0.5)
        try:
            val = max(0.0, min(100.0, float(gt.value)))
        except (TypeError, ValueError):
            val = 0.0
        # 半圆环：圆心在 (gcx, gcy-20)，从 180° 到 360°
        ccy = gcy - 20
        add_ring_segment(slide, gcx, ccy, Ro, ri, 180, 360, C.soft)
        if val > 0.5:
            add_ring_segment(slide, gcx, ccy, Ro, ri, 180, 180 + 180 * val / 100.0, accent)
        disp = gt.display or ("%s%%" % _fmt_num(gt.value))
        slide.add_text(disp, x=IN(gcx - 120), y=IN(gcy - 62), w=IN(240), h=IN(56),
                       fontSize=min(FS(34), fit_big_number(disp, 220, FS(34))), bold=True, color=accent,
                       fontFace=K.FONT, align="center", valign="middle")
        slide.add_text(gt.label, x=IN(gcx - zone_w / 2 + 20), y=IN(gcy + 22), w=IN(zone_w - 40), h=IN(56),
                       fontSize=FS(27), bold=True, color=C.deep, fontFace=K.FONT, align="center", valign="middle")
        if gt.target:
            slide.add_text(gt.target, x=IN(gcx - zone_w / 2 + 20), y=IN(gcy + 86), w=IN(zone_w - 40), h=IN(44),
                           fontSize=FS(20), color=C.gray, fontFace=K.FONT, align="center", valign="middle")


def _fmt_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return str(round(f, 2))


def add_org_tree(slide, page):
    org = page.org
    if not org or not org.groups:
        return
    groups = [AD(dict(g, members=(g.members or [])[:4])) for g in org.groups[:4]]
    n = len(groups)
    slide.add_text(org.root, shape="roundRect", x=IN(960 - 180), y=IN(236), w=IN(360), h=IN(84), fill={"color": C.deep},
                   line=NO_LINE, rectRadius=IN(10), fontSize=FS(28), bold=True, color=C.white, fontFace=K.FONT,
                   align="center", valign="middle")
    bus_y = 396
    slide.add_shape("line", x=IN(960), y=IN(320), w=0, h=IN(bus_y - 320), line={"color": C.gray, "width": 2})
    gw = AREA.w / float(n)
    centers = [AREA.x + gw * (i + 0.5) for i in range(n)]
    slide.add_shape("line", x=IN(centers[0]), y=IN(bus_y), w=IN(centers[-1] - centers[0]), h=0,
                    line={"color": C.gray, "width": 2})
    bw = min(gw - 56, 400)
    for i, g in enumerate(groups):
        gcx = centers[i]
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("line", x=IN(gcx), y=IN(bus_y), w=0, h=IN(32), line={"color": C.gray, "width": 2})
        slide.add_text(g.name, shape="roundRect", x=IN(gcx - bw / 2), y=IN(428), w=IN(bw), h=IN(68),
                       fill={"color": accent}, line=NO_LINE, rectRadius=IN(10), fontSize=FS(24), bold=True,
                       color=C.white, fontFace=K.FONT, align="center", valign="middle")
        for mi, m in enumerate(g.members):
            slide.add_text(m, shape="roundRect", x=IN(gcx - bw / 2), y=IN(528 + mi * 78), w=IN(bw), h=IN(64),
                           fill={"color": C.white}, line={"color": C.line, "width": 1}, rectRadius=IN(8),
                           shadow=card_shadow(), fontSize=FS(21), color=C.text, fontFace=K.FONT, align="center",
                           valign="middle")


def tint(hex_color, ratio):
    return mix(hex_color, "FFFFFF", ratio)


def add_onion(slide, page):
    layers = (page.layers or [])[:4]
    if not layers:
        return
    n = len(layers)
    ccx, ccy = 640, 596

    def radius(i):
        return 90 + i * 95

    def layer_color(i):
        return C.blue if i == 0 else tint(C.blue, min(0.82, 0.3 + (i - 1) * 0.24))

    for i in range(n - 1, -1, -1):
        Rr = radius(i)
        slide.add_shape("ellipse", x=IN(ccx - Rr), y=IN(ccy - Rr), w=IN(2 * Rr), h=IN(2 * Rr),
                        fill={"color": layer_color(i)}, line={"color": C.white, "width": 2})
    for i, l in enumerate(layers):
        Rr = radius(i)
        inner = i == 0
        slide.add_text(l.name, x=IN(ccx - 140), y=IN(ccy - 30 if inner else ccy - Rr + 14), w=IN(280), h=IN(60),
                       fontSize=FS(26 if inner else 21), bold=True, color=C.white if i <= 1 else C.deep,
                       fontFace=K.FONT, align="center", valign="middle")
    tx, top0 = 1160, 300
    for i, l in enumerate(layers):
        ry = top0 + i * 150
        slide.add_shape("ellipse", x=IN(tx), y=IN(ry + 6), w=IN(24), h=IN(24), fill={"color": layer_color(i)},
                        line={"color": C.line, "width": 1})
        slide.add_text(l.name, x=IN(tx + 44), y=IN(ry - 10), w=IN(640), h=IN(52), fontSize=FS(26), bold=True,
                       color=C.deep, fontFace=K.FONT, align="left", valign="middle")
        if l.desc:
            slide.add_text(l.desc, x=IN(tx + 44), y=IN(ry + 42), w=IN(640), h=IN(80), fontSize=FS(21), color=C.gray,
                           fontFace=K.FONT, align="left", valign="top", lineSpacingMultiple=1.3)


def add_cmp_table(slide, page):
    headers = (page.headers or [])[:4]
    rows = (page.rows or [])[:6]
    if len(headers) < 2 or not rows:
        return

    def mark(cell):
        t = cell.strip()
        if re.match(r"^[✓√✔]$", t):
            return "✓", C.green, True
        if re.match(r"^[✗✕×xX]$", t):
            return "✗", "D9534F", True
        if re.match(r"^[○◯~～]$", t):
            return "○", "E8A33D", True
        return cell, C.text, False

    header_row = [{"text": h, "options": {"fill": {"color": C.deep}, "color": C.white, "bold": True,
                                          "fontSize": FS(26)}} for h in headers]
    body = []
    for ri, r in enumerate(rows):
        row = []
        for ci in range(len(headers)):
            cell = str(r[ci]) if ci < len(r) and r[ci] is not None else ""
            fill = {"color": C.white if ri % 2 == 0 else C.soft}
            if ci == 0:
                row.append({"text": cell, "options": {"fill": fill, "color": C.deep, "bold": True, "fontSize": FS(22),
                                                      "align": "left"}})
                continue
            txt, col, b = mark(cell)
            row.append({"text": txt, "options": {"fill": fill, "color": col, "bold": b,
                                                 "fontSize": FS(20 if txt == cell and len(cell) > 2 else 26)}})
        body.append(row)
    first_w = IN(1776 * 0.32)
    rest_w = IN((1776 * 0.68) / (len(headers) - 1))
    slide.add_table([header_row] + body, x=IN(72), y=IN(230), w=IN(1776), colW=[first_w] + [rest_w] * (len(headers) - 1),
                    rowH=[IN(84)] + [IN(92)] * len(rows), fontFace=K.FONT, align="center", valign="middle",
                    border={"pt": 1, "color": C.line})


def add_faq(slide, page):
    faqs = (page.faqs or [])[:4]
    if not faqs:
        return
    n = len(faqs)
    gap = 26
    card_h = (716 - (n - 1) * gap) / float(n)
    for i, f in enumerate(faqs):
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        cy = 232 + i * (card_h + gap)
        slide.add_shape("roundRect", x=IN(AREA.x), y=IN(cy), w=IN(AREA.w), h=IN(card_h), fill={"color": C.white},
                        line={"color": C.line, "width": 1}, rectRadius=IN(12), shadow=card_shadow())
        slide.add_text("Q", shape="ellipse", x=IN(AREA.x + 30), y=IN(cy + 26), w=IN(56), h=IN(56), fill={"color": accent},
                       line=NO_LINE, fontSize=FS(28), bold=True, color=C.white, fontFace=K.FONT, align="center",
                       valign="middle", margin=0)
        slide.add_text(f.q, x=IN(AREA.x + 108), y=IN(cy + 26), w=IN(AREA.w - 150), h=IN(56), fontSize=FS(26), bold=True,
                       color=C.deep, fontFace=K.FONT, align="left", valign="middle")
        slide.add_text("A", shape="ellipse", x=IN(AREA.x + 30), y=IN(cy + 98), w=IN(56), h=IN(56), fill={"color": C.soft},
                       line=NO_LINE, fontSize=FS(28), bold=True, color=C.gray, fontFace=K.FONT, align="center",
                       valign="middle", margin=0)
        slide.add_text(f.a, x=IN(AREA.x + 108), y=IN(cy + 92), w=IN(AREA.w - 150), h=IN(card_h - 110), fontSize=FS(22),
                       color=C.text, fontFace=K.FONT, align="left", valign="top", lineSpacingMultiple=1.4)


# ── 图表 ─────────────────────────────────────────────────────

_ABS_RE = re.compile(r"合计|总计|期初|期末|净值")


def _finite(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def draw_waterfall(slide, chart, box):
    cats = (chart.categories or [])[:7]
    series = chart.series or []
    vals = ((series[0].get("values") if series else None) or [])[:7]
    if not cats:
        return
    cum = 0.0
    items = []
    for i, cat in enumerate(cats):
        v = _finite(vals[i] if i < len(vals) else 0)
        cat = str(cat)
        if i == 0 or _ABS_RE.search(cat):
            cum = v
            items.append(AD(cat=cat, v=v, base=0.0, top=v, abs=True))
            continue
        base, top = min(cum, cum + v), max(cum, cum + v)
        cum += v
        items.append(AD(cat=cat, v=v, base=base, top=top, abs=False))
    data_max = max(x.top for x in items)
    data_min = min([0.0] + [x.base for x in items] + [x.top for x in items])
    max_v = data_max * 1.14 if data_max > 0 else 0.0
    min_v = data_min
    if max_v <= min_v:
        min_v, max_v = -0.5, 0.5
    plot_x = box["x"] + 60
    plot_y = box["y"] + (80 if chart.title else 40)
    plot_w = box["w"] - 120
    plot_h = box["h"] - (190 if chart.title else 150)

    def y_of(v):
        return plot_y + plot_h * (1 - (v - min_v) / (max_v - min_v))

    if chart.title:
        slide.add_text(chart.title, x=IN(box["x"]), y=IN(box["y"] + 6), w=IN(box["w"]), h=IN(48), fontSize=FS(24),
                       bold=True, color=C.deep, fontFace=K.FONT, align="center", valign="middle")
    n = len(items)
    slot = plot_w / float(n)
    bar_w = slot * 0.56
    slide.add_shape("line", x=IN(plot_x), y=IN(y_of(0)), w=IN(plot_w), h=0, line={"color": C.line, "width": 2})

    def fmt_v(x):
        return _fmt_num(js_round(x * 100) / 100.0)

    for i, it in enumerate(items):
        bx = plot_x + i * slot + (slot - bar_w) / 2
        col = C.blue if it.abs else (C.green if it.v >= 0 else "D9534F")
        slide.add_shape("rect", x=IN(bx), y=IN(y_of(it.top)), w=IN(bar_w), h=IN(max(4, y_of(it.base) - y_of(it.top))),
                        fill={"color": col}, line=NO_LINE)
        if i > 0:
            pv = items[i - 1]
            prev_top = pv.top if (pv.abs or pv.v >= 0) else pv.base
            conn_y = prev_top if it.abs else (it.base if it.v >= 0 else it.top)
            slide.add_shape("line", x=IN(plot_x + (i - 1) * slot + (slot - bar_w) / 2 + bar_w),
                            y=IN(y_of(max(conn_y, prev_top))), w=IN(slot - bar_w), h=0,
                            line={"color": C.gray, "width": 1, "dashType": "dash"})
        label = fmt_v(it.v) if it.abs else ("+%s" % fmt_v(it.v) if it.v > 0 else fmt_v(it.v))
        slide.add_text(label, x=IN(bx - slot * 0.2), y=IN(y_of(it.top) - 44), w=IN(bar_w + slot * 0.4), h=IN(40),
                       fontSize=FS(18), bold=True, color=col, fontFace=K.FONT, align="center", valign="middle")
        slide.add_text(it.cat, x=IN(plot_x + i * slot), y=IN(y_of(0) + 12), w=IN(slot), h=IN(70), fontSize=FS(17),
                       color=C.text, fontFace=K.FONT, align="center", valign="top")


def add_chart(slide, chart, box):
    from . import charts
    if chart.kind == "waterfall":
        draw_waterfall(slide, chart, box)
        return
    charts.add_native_chart(slide, chart, box, K, C)


def add_chart_page(slide, page):
    if not page.chart:
        return
    tks = (page.takeaways or [])[:3]
    if tks:
        add_chart(slide, page.chart, {"x": 72, "y": 200, "w": 1130, "h": 760})
        slide.add_shape("roundRect", x=IN(1260), y=IN(210), w=IN(588), h=IN(740), fill={"color": C.soft}, line=NO_LINE,
                        rectRadius=IN(10), shadow=card_shadow())
        slide.add_shape("roundRect", x=IN(1300), y=IN(254), w=IN(20), h=IN(20), fill={"color": C.blue}, line=NO_LINE,
                        rectRadius=IN(4))
        slide.add_text("要点结论", x=IN(1336), y=IN(240), w=IN(400), h=IN(48), fontSize=FS(28), bold=True, color=C.deep,
                       fontFace=K.FONT, align="left", valign="middle")
        slide.add_text(_bullet_runs(tks, C.blue, 16), x=IN(1296), y=IN(316), w=IN(516), h=IN(600), fontSize=FS(26),
                       fontFace=K.FONT, align="left", valign="top", lineSpacingMultiple=1.5)
    else:
        add_chart(slide, page.chart, {"x": 260, "y": 200, "w": 1400, "h": 760})


def add_combo(slide, page):
    stats = (page.stats or [])[:3]
    top, card_h, gap = 210, 230, 36
    for i, s in enumerate(stats):
        y = top + i * (card_h + gap)
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("roundRect", x=IN(72), y=IN(y), w=IN(560), h=IN(card_h), fill={"color": C.soft}, line=NO_LINE,
                        rectRadius=IN(10), shadow=card_shadow())
        slide.add_shape("roundRect", x=IN(104), y=IN(y + 28), w=IN(56), h=IN(8), fill={"color": accent}, line=NO_LINE,
                        rectRadius=IN(4))
        if s.icon is not None or K.icons_on:
            icon_badge(slide, s.icon, s.label, 632 - 32 - 64, y + 24, 64, accent, style="soft")
        slide.add_text([R(s.value, fontSize=min(FS(48), fit_big_number(s.value, 470, FS(48))), bold=True, color=accent)],
                       x=IN(104), y=IN(y + 52), w=IN(496), h=IN(64), fontFace=K.FONT, align="left", valign="middle")
        slide.add_text(s.label, x=IN(104), y=IN(y + 126), w=IN(496), h=IN(84), fontSize=FS(22), color=C.text,
                       fontFace=K.FONT, align="left", valign="top", lineSpacingMultiple=1.3)
    if page.chart:
        add_chart(slide, page.chart, {"x": 700, "y": 210, "w": 1148, "h": 740})


# ── 图片 ─────────────────────────────────────────────────────

def resolve_image_file(rel):
    """页内图片路径：绝对路径直接用；相对路径先按 deck.json 所在目录，再按当前目录解析"""
    r = str(rel or "").strip()
    if not r:
        return None
    if r.startswith("file://"):
        r = r[7:]
    cands = [r] if os.path.isabs(r) else [os.path.join(b, r) for b in (K.base_dir, os.getcwd()) if b]
    for c in cands:
        if os.path.isfile(c):
            return c
    K.warnings.append("图片不存在，已用占位框代替：%s" % r)
    return None


def _image_placeholder(slide, box, text, size=28):
    slide.add_shape("roundRect", x=IN(box["x"]), y=IN(box["y"]), w=IN(box["w"]), h=IN(box["h"]), fill={"color": C.soft},
                    line={"color": C.line, "width": 1.5, "dashType": "dash"}, rectRadius=IN(12))
    slide.add_text(text, x=IN(box["x"]), y=IN(box["y"]), w=IN(box["w"]), h=IN(box["h"]), fontSize=FS(size), color=C.gray,
                   fontFace=K.FONT, align="center", valign="middle")


def add_image_page(slide, page):
    rel = str(page.image or "").strip()
    caption = str(page.caption or "").strip()
    box = {"x": 110, "y": 196, "w": 1700, "h": 690 if caption else 760}
    abs_ = resolve_image_file(rel)
    if abs_:
        slide.add_image(path=abs_, x=IN(box["x"]), y=IN(box["y"]), w=IN(box["w"]), h=IN(box["h"]),
                        sizing={"type": "contain"})
    else:
        _image_placeholder(slide, box, "图片文件缺失，请重新上传" if rel else "未选择图片")
    if caption:
        slide.add_text(caption, x=IN(110), y=IN(896), w=IN(1700), h=IN(56), fontSize=FS(22), color=C.gray,
                       fontFace=K.FONT, align="center", valign="middle")


# ── 金字塔 / 漏斗 / 循环 / 箭头流程 ────────────────────────────

def add_layer_tower(slide, page, inverted):
    layers = (page.layers or [])[:5]
    if not layers:
        return
    n = len(layers)
    box = AD(x=180, y=246, w=680, h=620)
    cx = box.w / 2.0
    y0 = 10
    H = box.h - 20
    max_w = 640
    min_ratio = 0.16 if inverted else 0

    def width_at(y):
        t = min(1.0, max(0.0, (y - y0) / float(H)))
        return max_w * (1 - t * (1 - min_ratio)) if inverted else max_w * t

    gap = 8
    for i in range(n):
        yt = y0 + i * H / float(n)
        yb = y0 + (i + 1) * H / float(n) - gap
        wt, wb = width_at(yt), width_at(yb)
        pts = [(cx - wt / 2, yt), (cx + wt / 2, yt), (cx + wb / 2, yb), (cx - wb / 2, yb)]
        if wt < 0.5:  # 金字塔尖顶：三角形
            pts = [(cx, yt), (cx + wb / 2, yb), (cx - wb / 2, yb)]
        p = Path().polygon(pts)
        x0, py0, x1, py1 = p.bbox()
        slide.add_custom(p, local=(x0, py0, x1 - x0, py1 - py0), x=IN(box.x + x0), y=IN(box.y + py0), w=IN(x1 - x0),
                         h=IN(py1 - py0), fill={"color": K.ACCENTS[i % len(K.ACCENTS)]}, line=NO_LINE)
    tx = 1010
    for i, l in enumerate(layers):
        mid_y = box.y + ((i + 0.5) * H) / n + y0
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        slide.add_shape("rect", x=IN(tx), y=IN(mid_y - 34), w=IN(22), h=IN(22), fill={"color": accent}, line=NO_LINE)
        slide.add_text(l.name, x=IN(tx + 42), y=IN(mid_y - 52), w=IN(780), h=IN(52), fontSize=FS(28), bold=True,
                       color=C.deep, fontFace=K.FONT, align="left", valign="middle")
        if l.desc:
            slide.add_text(l.desc, x=IN(tx + 42), y=IN(mid_y + 2), w=IN(780), h=IN(64), fontSize=FS(22), color=C.gray,
                           fontFace=K.FONT, align="left", valign="top", lineSpacingMultiple=1.35)


def add_pyramid(slide, page):
    add_layer_tower(slide, page, False)


def add_funnel(slide, page):
    add_layer_tower(slide, page, True)


def add_cycle(slide, page):
    steps = (page.steps or [])[:6]
    if not steps:
        return
    n = len(steps)
    box = AD(x=260, y=230, w=760, h=720)
    Ro, ri = 300, 175
    gap = 6.0
    abs_cx = box.x + box.w / 2.0
    abs_cy = box.y + box.h / 2.0
    mids = []
    for i in range(n):
        a0 = -90 + i * 360.0 / n + gap / 2
        a1 = -90 + (i + 1) * 360.0 / n - gap / 2
        mids.append(math.radians((a0 + a1) / 2))
        add_ring_segment(slide, abs_cx, abs_cy, Ro, ri, a0, a1, K.ACCENTS[i % len(K.ACCENTS)])
    slide.add_text("%d 步" % n, shape="ellipse", x=IN(abs_cx - ri + 30), y=IN(abs_cy - ri + 30), w=IN((ri - 30) * 2),
                   h=IN((ri - 30) * 2), fill={"color": C.soft}, line=NO_LINE, fontSize=FS(30), bold=True, color=C.gray,
                   fontFace=K.FONT, align="center", valign="middle")
    for i, st in enumerate(steps):
        mid = mids[i]
        mr = (Ro + ri) / 2.0
        nx = abs_cx + mr * math.cos(mid)
        ny = abs_cy + mr * math.sin(mid)
        slide.add_text(str(i + 1), x=IN(nx - 40), y=IN(ny - 40), w=IN(80), h=IN(80), fontSize=FS(34), bold=True,
                       color=C.white, fontFace=K.FONT, align="center", valign="middle")
        lr = Ro + 60
        lx = abs_cx + lr * math.cos(mid)
        ly = abs_cy + lr * math.sin(mid)
        cos = math.cos(mid)
        bw = 330
        raw = lx if cos > 0.25 else (lx - bw if cos < -0.25 else lx - bw / 2.0)
        bx = max(30, min(1880 - bw, raw))
        align = "left" if cos > 0.25 else ("right" if cos < -0.25 else "center")
        slide.add_text(st.title, x=IN(bx), y=IN(ly - 56), w=IN(bw), h=IN(52), fontSize=FS(27), bold=True,
                       color=K.ACCENTS[i % len(K.ACCENTS)], fontFace=K.FONT, align=align, valign="middle")
        if st.desc:
            slide.add_text(st.desc, x=IN(bx), y=IN(ly - 2), w=IN(bw), h=IN(90), fontSize=FS(21), color=C.text,
                           fontFace=K.FONT, align=align, valign="top", lineSpacingMultiple=1.3)


def add_arrow_flow(slide, page):
    steps = (page.steps or [])[:6]
    if not steps:
        return
    n = len(steps)
    overlap, y, h = 26, 400, 170
    w = (AREA.w + (n - 1) * overlap) / float(n)
    for i, st in enumerate(steps):
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        cx = AREA.x + i * (w - overlap)
        slide.add_text(st.title, shape="homePlate" if i == 0 else "chevron", x=IN(cx), y=IN(y), w=IN(w), h=IN(h),
                       fill={"color": accent}, line=NO_LINE, fontSize=FS(26), bold=True, color=C.white,
                       fontFace=K.FONT, align="center", valign="middle")
        if st.desc:
            slide.add_text(st.desc, x=IN(cx + 10), y=IN(y + h + 30), w=IN(w - 20), h=IN(200), fontSize=FS(21),
                           color=C.text, fontFace=K.FONT, align="center", valign="top", lineSpacingMultiple=1.4)


# ── 多栏卡片 / 图标要点 / 图文混排 ─────────────────────────────

def add_columns(slide, page):
    cols = (page.cols or [])[:4]
    if not cols:
        return
    n = len(cols)
    gap = 36
    cw = (AREA.w - (n - 1) * gap) / float(n)
    card_y, card_h = 246, 620
    for i, col in enumerate(cols):
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        cx = AREA.x + i * (cw + gap)
        img = resolve_image_file(col.image) if col.image else None
        slide.add_shape("roundRect", x=IN(cx), y=IN(card_y), w=IN(cw), h=IN(card_h), fill={"color": C.white},
                        line={"color": C.line, "width": 1}, rectRadius=IN(14), shadow=card_shadow())
        slide.add_shape("rect", x=IN(cx), y=IN(card_y), w=IN(cw), h=IN(10), fill={"color": accent}, line=NO_LINE)
        if img:
            slide.add_image(path=img, x=IN(cx + 24), y=IN(card_y + 34), w=IN(cw - 48), h=IN(240),
                            sizing={"type": "contain"})
            head_y = card_y + 296
        else:
            if col.icon or K.icons_on:
                icon_badge(slide, col.icon, col.heading, cx + cw / 2 - 46, card_y + 48, 92, accent,
                           fallback_text=str(i + 1))
            else:
                slide.add_text(str(i + 1), shape="ellipse", x=IN(cx + cw / 2 - 46), y=IN(card_y + 48), w=IN(92),
                               h=IN(92), fill={"color": accent}, line=NO_LINE, fontSize=FS(40), bold=True,
                               color=C.white, fontFace=K.FONT, align="center", valign="middle", margin=0)
            head_y = card_y + 166
        slide.add_text(col.heading, x=IN(cx + 28), y=IN(head_y), w=IN(cw - 56), h=IN(56), fontSize=FS(30), bold=True,
                       color=C.deep, fontFace=K.FONT, align="center", valign="middle")
        slide.add_text(col.text, x=IN(cx + 36), y=IN(head_y + 70), w=IN(cw - 72), h=IN(card_y + card_h - head_y - 96),
                       fontSize=FS(22), color=C.text, fontFace=K.FONT, align="center", valign="top",
                       lineSpacingMultiple=1.5)


def add_icon_list(slide, page):
    rows = (page.iconItems or [])[:6]
    if not rows:
        return
    n = len(rows)
    gap, top = 22, 230
    row_h = min(140, (736 - (n - 1) * gap) / float(n))
    for i, r in enumerate(rows):
        accent = K.ACCENTS[i % len(K.ACCENTS)]
        ry = top + i * (row_h + gap)
        slide.add_shape("roundRect", x=IN(AREA.x), y=IN(ry), w=IN(AREA.w), h=IN(row_h), fill={"color": C.white},
                        line={"color": C.line, "width": 1}, rectRadius=IN(12), shadow=card_shadow())
        icon_badge(slide, r.icon, r.heading, AREA.x + 34, ry + row_h / 2 - 36, 72, accent)
        slide.add_text(r.heading, x=IN(AREA.x + 140), y=IN(ry), w=IN(480), h=IN(row_h), fontSize=FS(28), bold=True,
                       color=C.deep, fontFace=K.FONT, align="left", valign="middle")
        slide.add_text(r.desc, x=IN(AREA.x + 640), y=IN(ry), w=IN(AREA.w - 640 - 40), h=IN(row_h), fontSize=FS(23),
                       color=C.text, fontFace=K.FONT, align="left", valign="middle", lineSpacingMultiple=1.4)


def add_image_text(slide, page):
    d = page.direction or "left"
    items = (page.get("items") or [])[:5]
    hz = d != "top"
    img_box = {"x": 72 if d == "left" else 1008, "y": 236, "w": 840, "h": 620} if hz else \
        {"x": 360, "y": 220, "w": 1200, "h": 420}
    txt = AD(x=1008 if d == "left" else 72, y=260, w=840, h=580) if hz else AD(x=160, y=680, w=1600, h=300)
    abs_ = resolve_image_file(page.image) if page.image else None
    if abs_:
        slide.add_image(path=abs_, x=IN(img_box["x"]), y=IN(img_box["y"]), w=IN(img_box["w"]), h=IN(img_box["h"]),
                        sizing={"type": "contain"})
    else:
        _image_placeholder(slide, img_box, "未选择图片", 26)
    if page.caption:
        slide.add_text(page.caption, x=IN(img_box["x"]), y=IN(img_box["y"] + img_box["h"] + 8), w=IN(img_box["w"]),
                       h=IN(40), fontSize=FS(20), color=C.gray, fontFace=K.FONT, align="center", valign="middle")
    row_h = min(96, (txt.h - 20) / float(max(len(items), 1))) if hz else 72
    for i, it in enumerate(items):
        ry = txt.y + i * row_h
        slide.add_shape("rect", x=IN(txt.x), y=IN(ry + row_h / 2 - 9), w=IN(18), h=IN(18),
                        fill={"color": K.ACCENTS[i % len(K.ACCENTS)]}, line=NO_LINE)
        slide.add_text(item_text_of(it), x=IN(txt.x + 40), y=IN(ry), w=IN(txt.w - 40), h=IN(row_h),
                       fontSize=FS(25 if hz else 23), color=C.text, fontFace=K.FONT, align="left", valign="middle",
                       lineSpacingMultiple=1.35)


# ── composite 复合区块页 ─────────────────────────────────────

def block_raw_height(b):
    k = b.kind
    if k == "paragraph":
        return 130
    if k == "statCards":
        return (52 if b.title else 0) + 220
    if k == "banner":
        return 260 if b.stats else 190
    if k == "bullets":
        return 24 + 52 * (len(b.get("items") or []) if b.get("items") is not None else 3)
    if k == "table":
        return (48 if b.title else 0) + 68 + 54 * (len(b.rows) if b.rows is not None else 3)
    return 130


def add_composite_block(slide, block, top, h):
    X, W = AREA.x, AREA.w
    k = block.kind
    if k == "paragraph":
        runs = [R(seg.text, color=C.primary if seg.emphasis else C.text, bold=bool(seg.emphasis))
                for seg in (block.segments or [])]
        slide.add_text(runs, x=IN(X), y=IN(top), w=IN(W), h=IN(h), fontSize=FS(26), fontFace=K.FONT, align="left",
                       valign="top", lineSpacingMultiple=1.5)
    elif k == "statCards":
        stats = (block.stats or [])[:4]
        if not stats:
            return
        title_h = 52 if block.title else 0
        if block.title:
            slide.add_text(block.title, x=IN(X), y=IN(top), w=IN(W), h=IN(title_h), fontSize=FS(26), bold=True,
                           color=C.deep, fontFace=K.FONT, align="left", valign="middle")
        gap = 28
        cw = (W - (len(stats) - 1) * gap) / float(len(stats))
        card_h = h - title_h
        for si, st in enumerate(stats):
            cx = X + si * (cw + gap)
            slide.add_shape("roundRect", x=IN(cx), y=IN(top + title_h), w=IN(cw), h=IN(card_h), fill={"color": C.white},
                            line={"color": C.line, "width": 1}, rectRadius=IN(10), shadow=card_shadow())
            slide.add_shape("rect", x=IN(cx), y=IN(top + title_h), w=IN(cw), h=IN(6),
                            fill={"color": K.ACCENTS[si % len(K.ACCENTS)]}, line=NO_LINE)
            slide.add_text(st.value, x=IN(cx), y=IN(top + title_h + card_h * 0.18), w=IN(cw), h=IN(card_h * 0.42),
                           fontSize=min(FS(48), fit_big_number(st.value, cw - 40, FS(48))), bold=True, color=C.blue,
                           fontFace=K.FONT, align="center", valign="middle")
            slide.add_text(st.label, x=IN(cx), y=IN(top + title_h + card_h * 0.62), w=IN(cw), h=IN(card_h * 0.26),
                           fontSize=FS(22), color=C.gray, fontFace=K.FONT, align="center", valign="middle")
    elif k == "banner":
        stats = (block.stats or [])[:3]
        slide.add_shape("rect", x=IN(X), y=IN(top), w=IN(W), h=IN(h), fill=grad(C.primary, C.blue, C.mid), line=NO_LINE)
        text_w = 700 if stats else W - 96
        runs = [R(block.title, fontSize=FS(30), bold=True, color=C.white, breakLine=True)]
        if block.desc:
            runs.append(R(block.desc, fontSize=FS(20), color="E8F4F5", breakLine=True))
        slide.add_text(runs, x=IN(X + 48), y=IN(top), w=IN(text_w), h=IN(h), fontFace=K.FONT, align="left",
                       valign="middle", lineSpacingMultiple=1.4)
        if stats:
            sw = 300
            sx0 = X + W - 48 - len(stats) * sw
            for si, st in enumerate(stats):
                sx = sx0 + si * sw
                if si > 0:
                    slide.add_shape("line", x=IN(sx), y=IN(top + h * 0.27), w=0, h=IN(h * 0.46),
                                    line={"color": "9FD3D9", "width": 0.75})
                slide.add_text([R(st.value, fontSize=min(FS(44), fit_big_number(st.value, 260, FS(44))), bold=True,
                                  color=C.white, breakLine=True),
                                R(st.label, fontSize=FS(18), color="E8F4F5")],
                               x=IN(sx), y=IN(top), w=IN(sw), h=IN(h), fontFace=K.FONT, align="center",
                               valign="middle", lineSpacingMultiple=1.3)
    elif k == "bullets":
        items = block.get("items") or []
        runs = []
        for ii, it in enumerate(items):
            runs.append(R("●  ", color=K.ACCENTS[ii % len(K.ACCENTS)], bold=True))
            runs.append(R(item_text_of(it), color=C.text, breakLine=True))
            if ii < len(items) - 1:
                runs.append(R(" ", fontSize=FS(10), breakLine=True))
        slide.add_text(runs, x=IN(X), y=IN(top), w=IN(W), h=IN(h), fontSize=FS(25), fontFace=K.FONT, align="left",
                       valign="middle", lineSpacingMultiple=1.4)
    elif k == "table":
        headers = block.headers or []
        rows = (block.rows or [])[:5]
        if not headers:
            return
        title_h = 48 if block.title else 0
        if block.title:
            slide.add_text(block.title, x=IN(X), y=IN(top), w=IN(W), h=IN(title_h), fontSize=FS(24), bold=True,
                           color=C.deep, fontFace=K.FONT, align="left", valign="middle")
        tbl_h = h - title_h
        header_row = [{"text": hd, "options": {"fill": {"color": C.deep}, "color": C.white, "bold": True,
                                               "fontSize": FS(22)}} for hd in headers]
        body = [[{"text": (r[ci] if ci < len(r) and r[ci] is not None else ""),
                  "options": {"fill": {"color": C.white if ri % 2 == 0 else C.soft},
                              "color": C.deep if ci == 0 else C.text, "bold": ci == 0, "fontSize": FS(20)}}
                 for ci in range(len(headers))] for ri, r in enumerate(rows)]
        head_h = min(68, tbl_h * 0.22)
        slide.add_table([header_row] + body, x=IN(X), y=IN(top + title_h), w=IN(W),
                        colW=[IN(W) / len(headers)] * len(headers),
                        rowH=[IN(head_h)] + [IN((tbl_h - head_h) / max(1, len(rows)))] * len(rows), fontFace=K.FONT,
                        align="center", valign="middle", border={"pt": 1, "color": C.line})


def add_composite(slide, page):
    area_h = 654 if has_takeaways(page) else AREA.h
    blocks = (page.blocks or [])[:4]
    if not blocks:
        return
    gap = 24
    raw = sum(block_raw_height(b) for b in blocks)
    avail = area_h - gap * (len(blocks) - 1)
    k = avail / float(raw) if raw > 0 else 1
    y = AREA.y
    for b in blocks:
        h = js_round(block_raw_height(b) * k)
        add_composite_block(slide, b, y, h)
        y += h + gap
    add_takeaways_bar(slide, page)


# ── design 自由设计页 ────────────────────────────────────────

_HEX6 = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def design_color(v):
    if not v:
        return None
    v = str(v)
    if _HEX6.match(v):
        return v.lstrip("#").upper()
    c = C.get(v)
    return c.upper() if c else None


def _estimate_lines(text, size, box_w):
    """按真实字宽估算折行行数（单位：设计稿 px）"""
    lines = 1
    cur = 0.0
    cap = float(box_w)
    for ch in text:
        if ch == "\n":
            lines += 1
            cur = 0.0
            continue
        w = fontmetrics.char_em(ch, K.FONT, K.LATIN) * size
        cur += w
        if cur > cap:
            lines += 1
            cur = w
    return lines


def _estimate_runs_height(runs, box_w, ls):
    lines = [[]]
    for r in runs:
        parts = str(r.text or "").split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                lines.append([])
            if part:
                lines[-1].append((part, r.size))
        if r.breakLine:
            lines.append([])
    total = 0.0
    for segs in lines:
        if not segs:
            total += 18 * ls
            continue
        mx = max(s for _, s in segs)
        total += _estimate_lines("".join(t for t, _ in segs), mx, box_w) * mx * ls
    return total


MIN_SHRINK_SIZE = 12


def autofit_design_element_text(el):
    """渲染前确定性缩字：单行缩到框宽放得下，多行缩到框高 ×0.92；只缩不放"""
    if el.kind != "text" or not el.runs:
        return False
    _, _, w, h = el.bounds
    if w <= 0 or h <= 0:
        return False
    ls = el.lineSpacing or 1.2
    single = not any("\n" in str(r.text or "") or r.breakLine for r in el.runs)
    k = 1.0
    inner_w = max(1.0, w - 14.4)  # 文本框左右默认内边距约 0.1in×2 ≈ 14.4px（设计稿）——这里只扣一半留余量
    if single:
        used = sum(fontmetrics.char_em(ch, K.FONT, K.LATIN) * r.size for r in el.runs for ch in str(r.text or ""))
        if used > inner_w:
            k = min(k, inner_w / used * 0.96)
    else:
        need = _estimate_runs_height(el.runs, inner_w, ls)
        if need > h * 0.92:
            k = min(k, h * 0.92 / need)
    if k >= 0.999:
        return False
    mx = max(r.size for r in el.runs)
    if mx * k < MIN_SHRINK_SIZE:
        return False
    for r in el.runs:
        r["size"] = max(MIN_SHRINK_SIZE, js_round(r.size * k))
    if single:
        el["wrap"] = False
    return True


def add_design(slide, page):
    from . import icons
    for el in page.elements or []:
        b = list(el.bounds or [0, 0, 0, 0]) + [0, 0, 0, 0]
        x, y, w, h = [float(v or 0) for v in b[:4]]
        box = dict(x=IN(x), y=IN(y), w=IN(w), h=IN(h))
        kind = el.kind
        if kind == "shape":
            if el.gradient:
                stops = [{"pos": min(max(float(s.pos or 0), 0), 1) * 100, "color": design_color(s.color) or "FFFFFF"}
                         for s in (el.gradient.stops or [])]
                geom = el.shape if el.shape in ("ellipse", "roundRect") else "rect"
                extra = {"rectRadius": IN(el.radius if el.radius is not None else 12)} if geom == "roundRect" else {}
                slide.add_shape(geom, fill={"type": "grad", "stops": stops, "ang": el.gradient.angle or 0}, line=NO_LINE,
                                **dict(box, **extra))
                continue
            if el.shape == "line":
                horiz = h == 0
                slide.add_shape("line", x=box["x"], y=box["y"], w=box["w"] if horiz else 0, h=0 if horiz else box["h"],
                                line={"color": design_color((el.line or AD()).color or el.fill) or C.line,
                                      "width": (el.line or AD()).width or 2})
                continue
            geom = "ellipse" if el.shape == "ellipse" else ("roundRect" if el.shape == "roundRect" else "rect")
            extra = {"rectRadius": IN(el.radius if el.radius is not None else 12)} if geom == "roundRect" else {}
            slide.add_shape(geom, fill={"color": design_color(el.fill) or "FFFFFF"},
                            line={"color": design_color(el.line.color) or C.line, "width": el.line.width}
                            if el.line else NO_LINE, **dict(box, **extra))
            continue
        if kind == "text":
            bumped = el.get("_bumped", False)
            runs = [R(r.text, fontSize=FS(clamp_text_px(r.size or 18)), bold=bool(r.bold),
                      color=design_color(r.color) or C.text, fontFace=K.FONT, breakLine=bool(r.breakLine))
                    for r in el.runs or []]
            wrap = True if (el.wrap is False and bumped) else (el.wrap if el.wrap is not None else True)
            valign = el.valign if el.valign in ("middle", "bottom") else "top"
            slide.add_text(runs, align=el.align or "left", valign=valign, lineSpacingMultiple=el.lineSpacing or 1.2,
                           wrap=wrap, fontFace=K.FONT, **box)
            continue
        if kind == "image":
            abs_ = resolve_image_file(el.path)
            if abs_:
                slide.add_image(path=abs_, sizing={"type": el.fit} if el.fit in ("cover", "contain") else None, **box)
            else:
                _image_placeholder(slide, {"x": x, "y": y, "w": w, "h": h}, "图片文件缺失", 24)
            continue
        if kind == "icon":
            color = design_color(el.color) or C.primary
            if not icons.draw_icon(slide, el.name, x, y, w, h, color):
                slide.add_text(el.name, fontSize=FS(min(w, h) * 0.55), color=color, fontFace=K.FONT, align="center",
                               valign="middle", **box)
            continue
        if kind == "table":
            add_design_table(slide, el, x, y, w, h)
            continue
        if kind == "chart" and el.chart:
            add_chart(slide, el.chart, {"x": x, "y": y, "w": w, "h": h})


def add_design_table(slide, el, x, y, w, h):
    cells = [list(r or []) for r in (el.cells or []) if isinstance(r, list)]
    if not cells:
        return
    ncol = max(len(r) for r in cells) or 1
    header = el.header is not False
    size = clamp_text_px(el.size or 20)
    color = design_color(el.color) or C.text
    head_fill = design_color(el.headerFill) or C.deep
    border = design_color(el.borderColor) or C.line
    rows = []
    for ri, r in enumerate(cells):
        row = []
        for ci in range(ncol):
            t = str(r[ci]) if ci < len(r) and r[ci] is not None else ""
            if header and ri == 0:
                row.append({"text": t, "options": {"fill": {"color": head_fill}, "color": C.white, "bold": True,
                                                   "fontSize": FS(size)}})
            else:
                zebra = (ri - (1 if header else 0)) % 2 == 1
                row.append({"text": t, "options": {"fill": {"color": C.soft if zebra else C.white}, "color": color,
                                                   "bold": False, "fontSize": FS(size)}})
        rows.append(row)
    rh = h / float(len(cells))
    slide.add_table(rows, x=IN(x), y=IN(y), w=IN(w), colW=[IN(w) / ncol] * ncol, rowH=[IN(rh)] * len(cells),
                    fontFace=K.FONT, align="center", valign="middle", border={"pt": 1, "color": border},
                    margin=[0.03, 0.06, 0.03, 0.06])


# ── 图标徽章 ─────────────────────────────────────────────────

def icon_badge(slide, icon, text, x, y, size, color, style="solid", fallback_text=None):
    """图标徽章：solid=主题色圆 + 白色图标；soft=浅色圆 + 彩色图标；glyph=只画图标。
    icon 可为图标 id / emoji / 空（按 text 自动选）。返回是否画成。"""
    from . import icons
    used = K.page_icons
    auto = K.icons_on or icon is not None
    iid = icons.resolve(icon, text, used, auto=auto)
    if not iid:
        if fallback_text is None:
            return False
        slide.add_text(fallback_text, shape="ellipse", x=IN(x), y=IN(y), w=IN(size), h=IN(size), fill={"color": color},
                       line=NO_LINE, fontSize=FS(size * 0.43), bold=True, color=C.white, fontFace=K.FONT,
                       align="center", valign="middle", margin=0)
        return True
    used.add(iid)
    if style == "glyph":
        return icons.draw_icon_id(slide, iid, x, y, size, size, color)
    bg = color if style == "solid" else tint(color, 0.86)
    fg = C.white if style == "solid" else color
    slide.add_shape("ellipse", x=IN(x), y=IN(y), w=IN(size), h=IN(size), fill={"color": bg}, line=NO_LINE)
    inner = size * 0.5
    return icons.draw_icon_id(slide, iid, x + (size - inner) / 2, y + (size - inner) / 2, inner, inner, fg)


# ── 渲染主流程 ───────────────────────────────────────────────

def brand_locked(theme):
    if os.environ.get("PPT_BRAND_LOCK") == "off":
        return False
    t = ad(theme or DEFAULT_THEME)
    a = t.assets or AD()
    return bool(a.contentBg or a.headerShapes or a.chapterBg or a.coverBg)


_PAGE_FNS = {
    "bullets": add_bullets, "stats": add_stats, "compare": add_compare, "table": add_table_page,
    "chart": add_chart_page, "combo": add_combo, "steps": add_steps, "matrix": add_matrix, "timeline": add_timeline,
    "quote": add_quote, "image": add_image_page, "columns": add_columns, "iconlist": add_icon_list,
    "imagetext": add_image_text, "pyramid": add_pyramid, "funnel": add_funnel, "cycle": add_cycle,
    "arrowflow": add_arrow_flow, "gantt": add_gantt, "kpi": add_kpi, "orgtree": add_org_tree, "onion": add_onion,
    "cmptable": add_cmp_table, "faq": add_faq, "composite": add_composite, "design": add_design,
}


def build_layouts(pres):
    """按当前模板（template.json + 素材）生成版式：封面 / 内容页 / 章节页 / 封底 → {页型: 版式序号}"""
    from .layouts import body_placeholder, PROMPT
    out = {}
    n, c = pres.add_layout("封面", "title", "ctrTitle")
    c.background = C.white
    add_cover(c, ad({"type": "cover", "title": PROMPT["title"]}))
    out["cover"] = n
    n, c = pres.add_layout("标题和内容", "obj", "title")
    c.background = C.white
    add_header(c, PROMPT["title"])
    pres.layouts[-1]["extra"].append(body_placeholder(2000, IN(AREA.x), IN(AREA.y), IN(AREA.w), IN(AREA.h), K.FONT, K.LATIN,
                                                      C.text or "424242"))
    out["content"] = n
    n, c = pres.add_layout("章节页", "secHead", "title")
    c.background = C.white
    add_chapter(c, ad({"type": "chapter", "part": 1, "title": PROMPT["title"]}))
    out["chapter"] = n
    n, c = pres.add_layout("封底", "titleOnly", "title")
    c.background = C.white
    add_end(c, ad({"type": "end", "title": "谢谢"}))
    out["end"] = n
    K.warnings = []
    return out


def render_pages(pres, pages, theme=None, opts=None):
    """把（已规范化的）页面画进 Presentation。opts: noPageFooter, variants('auto'|'off'), icons('auto'|'off'),
    baseDir（相对图片路径的基准目录）, fonts。返回告警列表。"""
    import copy
    from . import render_variants as RV
    from .variants import resolve_variants

    opts = opts or {}
    pages = ad(copy.deepcopy(pages))
    apply_theme(theme, opts.get("fonts"))
    K.show_footer = not opts.get("noPageFooter")
    K.base_dir = opts.get("baseDir")
    K.icons_on = str(opts.get("icons", "auto")).lower() not in ("off", "false", "0", "none")
    if K.LATIN:
        pres.latin_fonts[K.FONT] = K.LATIN
        pres.latin_fonts[K.FONT_HEI] = K.LATIN
    # design 页：字号下限先于 autofit
    for p in pages:
        if p.type != "design":
            continue
        for el in p.elements or []:
            if el.kind == "text":
                for r in el.runs or []:
                    if (r.size or 18) < MIN_TEXT_PX:
                        el["_bumped"] = True
                    r["size"] = clamp_text_px(r.size or 18)
                autofit_design_element_text(el)
    if str(opts.get("variants", "auto")).lower() == "off" or os.environ.get("PPT_VARIANTS") == "off":
        variants = ["default"] * len(pages)
    else:
        variants = resolve_variants(pages)
    kit = RV.Kit(C, K.FONT, K.LATIN, brand_locked(theme),
                 None, K.show_footer,
                 add_header, add_footer, add_chart, resolve_image_file, icon_badge, K.icons_on)
    layout_of = {}
    if opts.get("layouts", True) is not False:
        layout_of = build_layouts(pres)
        pres.show_master_sp = False  # 成品页已画好模板外观，隐藏版式图形，避免画两遍
    page_no = 0
    chapter_kicker = None
    for pi, page in enumerate(pages):
        slide = pres.add_slide()
        slide.background = C.white
        if layout_of:
            kind = page.type if page.type in ("cover", "chapter", "end") else "content"
            slide.set_layout(layout_of[kind])
            slide.title_ph = "ctrTitle" if page.type == "cover" else "title"
        K.page_icons = set()
        ptype = page.type
        if ptype == "chapter":
            chapter_kicker = ("%s · %s" % (page.partText or "PART %s" % ("" if page.part is None else page.part),
                                           page.title or "")).strip()
        variant = variants[pi]
        if variant != "default":
            if RV.render_variant(slide, kit, page, variant, page_no + 1, page.kicker or chapter_kicker):
                page_no += 1
                continue
        if ptype == "cover":
            add_cover(slide, page)
        elif ptype == "chapter":
            add_chapter(slide, page)
        elif ptype == "end":
            add_end(slide, page)
        elif ptype == "toc":
            page_no += 1
            add_header(slide, page.title or "目录")
            add_toc(slide, page)
        else:
            fn = _PAGE_FNS.get(ptype)
            if fn is None:
                page = coerce_to_bullets(page)
                fn = add_bullets
            page_no += 1
            add_header(slide, page.title or "未命名")
            fn(slide, page)
            add_footer(slide, page.note, page_no)
    return list(K.warnings)
