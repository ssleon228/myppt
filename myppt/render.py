"""实验版出稿主流程：每页按「AI 版面 → 程序设计 → 底层引擎 旧版式」三级决定怎么画。

1. 页面带 layout（AI 搭的积木）：先校验修正，再求解；放得下、不太空就用。
2. 否则（或 AI 版面不合格）：程序按页型生成几种候选版面，逐个求解打分，挑最好的。
3. 都不行：交给 底层引擎 原来的版式（保证不出烂页）。
封面、目录、章节、封底和 底层引擎 选中的「强视觉页」（深色金句、整版图片等）仍由 底层引擎 画，保持整套节奏。
"""
import copy
import json
import os

from .engine import api as PA
from .engine import render as PR
from .engine import render_variants as RV
from .engine.variants import resolve_variants, STRONG_VARIANTS, VARIANT_LABELS
from .engine.ooxml.package import Presentation

from . import blocks as B
from . import measure
from .autodesign import candidates, flatten_to_page
from .solver import Solver
from .spec import normalize, signature, family
from .tokens import palette, BASE_LEVEL, AREA
from . import styles as STY
from .engine.ooxml.util import mix

MIN_FILL_AI = 0.22
# 底层引擎 里「读懂了数据」的版式（高亮柱+注释、排名条、达标分色、箭头流程等）：程序设计不比它强，保留
SEMANTIC_VARIANTS = {"annotated", "ranking", "heat", "chevron", "roadmap", "dashboard"}


class Ctx:
    def __init__(self, slide, pal, font, latin, warns):
        self.slide = slide
        self.pal = pal
        self.font = font
        self.latin = latin
        self.dark_bg = None
        self._warns = warns

    def icon(self, icon, text, x, y, size, color, style="glyph"):
        """徽章类图标（solid/soft）按设计语言换画法：圆角方块 / 方块 / 细圆环 / 只画线条"""
        from .styles import CUR
        from .engine import icons as ICONS
        lang = CUR.get("icon") or "solid"
        if style in ("solid", "soft") and lang != "solid":
            iid = ICONS.resolve(icon, text, PR.K.page_icons, auto=True)
            if not iid:
                return False
            PR.K.page_icons.add(iid)
            if lang == "glyph":
                return ICONS.draw_icon_id(self.slide, iid, x + size * 0.1, y + size * 0.1, size * 0.8, size * 0.8, color)
            if lang == "ring":
                self.slide.add_shape("ellipse", x=x / 144.0, y=y / 144.0, w=size / 144.0, h=size / 144.0,
                                     fill={"type": "none"}, line={"color": self.pal.get("accent") or color, "width": 1.25})
                inner = size * 0.46
                return ICONS.draw_icon_id(self.slide, iid, x + (size - inner) / 2, y + (size - inner) / 2, inner, inner,
                                          self.pal.get("accent_text") or color)
            shape = "roundRect" if lang == "tile" else "rect"
            o = {"rectRadius": size * 0.24 / 144.0} if lang == "tile" else {}
            bg = color if style == "solid" else mix(color, "FFFFFF", 0.86)
            fg = "FFFFFF" if style == "solid" else color
            self.slide.add_shape(shape, x=x / 144.0, y=y / 144.0, w=size / 144.0, h=size / 144.0, fill={"color": bg},
                                 line={"type": "none"}, **o)
            inner = size * 0.5
            return ICONS.draw_icon_id(self.slide, iid, x + (size - inner) / 2, y + (size - inner) / 2, inner, inner, fg)
        return PR.icon_badge(self.slide, icon, text, x, y, size, color, style=style)

    def add_chart(self, slide, chart, box):
        PR.add_chart(slide, chart, box)

    def resolve_image(self, rel):
        return PR.resolve_image_file(rel) if rel else None

    def warn(self, msg):
        self._warns.append(msg)


# ── 打分 ─────────────────────────────────────────────

def score(res, prev_sig, sig, hist=(), fam=None, holes=0):
    rep = res["report"]
    s = 100.0
    fill = rep["fill"]
    if fill < 0.55:
        s -= (0.55 - fill) * 160
    if fill > 0.92:
        s -= (fill - 0.92) * 100
    L = rep["level"]
    s += (min(L, 5) - BASE_LEVEL) * 4 if L >= BASE_LEVEL else -(BASE_LEVEL - L) * 14
    for code, _ in rep["warnings"]:
        s -= {"imbalance": 12, "crowded": 10, "sparse": 8, "dense": 0, "card-empty": 14, "blank-band": 0}.get(code, 5)
    if prev_sig and sig == prev_sig:
        s -= 30
    if fam and hist:
        if hist[-1] == fam:
            s -= 18
        if len(hist) > 1 and hist[-2] == fam:
            s -= 8
        s -= 7 * sum(1 for h in hist if h == fam)  # 整套里用得越多越扣分
    s -= holes * 25  # 网格里有空位
    band = rep.get("band", 0)
    if band > 0.15:
        s -= (band - 0.15) * 220  # 半页空着：空白带越宽扣得越多
    return round(s, 1)


def _holes(n):
    if "el" in n:
        return 0
    return sum(1 for c in n["children"] if c.get("el") == "spacer") + sum(_holes(c) for c in n["children"] if "el" not in c)


def try_tree(tree):
    res = Solver(tree).solve()
    return res


def design_page(page, prev_sig, hist=()):
    """→ (来源说明, 树, 求解结果, 修正列表) 或 None（交给 底层引擎）"""
    notes = []
    lay = page.get("layout")
    if lay:
        tree, fixes, errors = normalize(lay)
        notes += ["修正 " + x for x in fixes]
        if tree is not None and not errors:
            STY.remap(tree)
            res = try_tree(tree)
            if res["ok"] and res["report"]["fill"] >= MIN_FILL_AI:
                return "AI版面", tree, res, notes
            notes.append("AI版面不合格（%s），改由程序设计" % (
                "放不下" if not res["ok"] else "太空，填充率 %d%%" % round(res["report"]["fill"] * 100)))
        else:
            notes += ["问题 " + x for x in errors]
            notes.append("AI版面结构有误，改由程序设计")
    src = page
    if page.get("type") == "free" or (lay and page.get("type") not in ("bullets", "stats", "columns", "iconlist",
                                                                          "compare", "steps", "chart", "combo", "table", "timeline",
                                                                          "matrix", "quote", "kpi", "imagetext", "faq")):
        src = flatten_to_page(lay, page.get("title"))
    best = None
    tried = []
    for name, tree in candidates(src):
        t2, fx, er = normalize(tree)
        if t2 is None or er:
            continue
        STY.remap(t2)
        STY.emphasize(t2)
        res = try_tree(t2)
        if not res["ok"]:
            tried.append("%s:放不下" % name)
            continue
        sig = signature(t2)
        sc = score(res, prev_sig, sig, hist, family(t2), _holes(t2)) + STY.bonus(name)
        tried.append("%s:%s" % (name, sc))
        if best is None or sc > best[0]:
            best = (sc, name, t2, res)
    if best is None:
        notes.append("程序候选都放不下（%s），用旧版式" % "、".join(tried) if tried else "没有可用候选，用旧版式")
        return None if not lay else ("fallback", None, None, notes)
    notes.append("候选 " + "、".join(tried))
    return "程序设计:" + best[1], best[2], best[3], notes


def draw_tree(slide, res, pal, warns):
    ctx = Ctx(slide, pal, PR.K.FONT, PR.K.LATIN, warns)
    from .blocks import IN
    blocks_seen = [0]
    for st, (x, y, w, h) in res["cards"]:
        if st == "soft":
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": pal["soft"]}, line={"type": "none"})
        elif st == "outline":
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": "FFFFFF"},
                            line={"color": pal["line"], "width": 1.25})
        elif st in ("accent", "dark"):
            fill = PR.grad(pal["primary"], pal.get("secondary") or pal["accent"], None, 60) if st == "accent" else {"color": pal["dark"]}
            if STY.CUR.get("id") == "rounded":
                slide.add_shape("roundRect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), rectRadius=IN(26), fill=fill,
                                line={"type": "none"}, shadow={"type": "outer", "color": pal["dark"], "blur": 18, "offset": 4,
                                                              "angle": 90, "opacity": 0.16})
            else:
                slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill=fill, line={"type": "none"})
        elif st == "topbar":
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": "FFFFFF"},
                            line={"color": pal["line"], "width": 0.75}, shadow=PR.card_shadow())
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(6), fill={"color": pal["primary"]}, line={"type": "none"})
        elif st == "leftbar":
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(6), h=IN(h), fill={"color": pal["primary"]}, line={"type": "none"})
        elif st in ("panel", "panel-light"):  # 通栏侧板：贴边的一侧铺到页面边缘，上下铺满内容区
            from . import tokens as TK
            A = TK.AREA
            x0 = 0 if x - A["x"] < 4 else x
            x1 = PR.PAGE_W if (x + w) > A["x"] + A["w"] - 4 else x + w
            if h > A["h"] * 0.8:
                y0, y1 = A["y"] - 30, min(1008, A["y"] + A["h"] + 8)
            else:
                y0, y1 = y, y + h
            fill = PR.grad(pal["primary"], pal["dark"], None, 70) if st == "panel" else {"color": pal["soft"]}
            slide.add_shape("rect", x=IN(x0), y=IN(y0), w=IN(x1 - x0), h=IN(y1 - y0), fill=fill, line={"type": "none"})
        elif st == "raised":  # 圆润：白色圆角卡浮起（页面底是浅色）
            slide.add_shape("roundRect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), rectRadius=IN(26), fill={"color": "FFFFFF"},
                            line={"type": "none"}, shadow={"type": "outer", "color": pal["dark"], "blur": 18, "offset": 4,
                                                          "angle": 90, "opacity": 0.10})
        elif st == "rule":  # 杂志：顶部一条细线 + 一小段粗色线
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(1.5), fill={"color": pal["ink"]}, line={"type": "none"})
            slide.add_shape("rect", x=IN(x), y=IN(y - 2), w=IN(min(64, w)), h=IN(6), fill={"color": pal.get("accent", pal["primary"])},
                            line={"type": "none"})
        elif st == "block":  # 大色块：轮流用主色 / 深色 / 辅色
            k = blocks_seen[0] % 3
            blocks_seen[0] += 1
            fill = [pal["primary"], pal["dark"], pal.get("secondary_text") or pal["primary"]][k]
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": fill}, line={"type": "none"})
        elif st == "fine":  # 典雅：金色细框 + 四角小菱形
            acc = pal.get("accent") or pal["primary"]
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"type": "none"}, line={"color": acc, "width": 0.75})
            for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                slide.add_shape("diamond", x=IN(cx - 6), y=IN(cy - 6), w=IN(12), h=IN(12), fill={"color": acc},
                                line={"type": "none"})
        elif st == "bracket":  # 科技：极浅底 + 四角折线角标
            slide.add_shape("rect", x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill={"color": pal["soft2"]}, line={"type": "none"})
            acc = pal.get("secondary") or pal["primary"]
            L_ = 26
            for cx, cy, dx, dy in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
                slide.add_shape("rect", x=IN(min(cx, cx + dx * L_)), y=IN(cy - (3 if dy < 0 else 0)), w=IN(L_), h=IN(3),
                                fill={"color": acc}, line={"type": "none"})
                slide.add_shape("rect", x=IN(cx - (3 if dx < 0 else 0)), y=IN(min(cy, cy + dy * L_)), w=IN(3), h=IN(L_),
                                fill={"color": acc}, line={"type": "none"})
    _watermarks(slide, res, pal)
    for n, box, tone, nat in res["leaves"]:
        if tone == "dark":
            ctx.dark_bg = pal["dark"] if STY.CUR.get("id") == "bold" else pal["primary"]
        B.DRAW[n["el"]](ctx, n, box, res["level"], tone)
    _seq_arrows(slide, res, pal)


_WM_STYLES = {"soft": "soft", "outline": "FFFFFF", "topbar": "FFFFFF", "raised": "FFFFFF", "bracket": "soft2", "block": None}


def _inside(b, c):
    return b[0] >= c[0] - 1 and b[1] >= c[1] - 1 and b[0] + b[2] <= c[0] + c[2] + 1 and b[1] + b[3] <= c[1] + c[3] + 1


def _watermarks(slide, res, pal):
    """水印大序号：一组 ≥3 张同尺寸卡片，右上角铺一个很淡的大号 01/02/03（卡片里已有编号的不加）"""
    if not STY.CUR.get("watermark"):
        return
    from .blocks import IN
    from .engine.ooxml.util import mix
    groups = {}
    for st, b in res["cards"]:
        groups.setdefault((round(b[2] / 6), round(b[3] / 6)), []).append((st, b))
    for _, members in groups.items():
        sts = set(m[0] for m in members)
        if len(sts) != 1 or list(sts)[0] not in _WM_STYLES:  # 同尺寸卡片里有一张被突出（主色）时不编号
            continue
        st = members[0][0]
        boxes = [m[1] for m in members]
        if not 3 <= len(boxes) <= 6:
            continue
        numbered = False
        for n, lb, tone, nat in res["leaves"]:
            if any(_inside(lb, c) for c in boxes) and (n["el"] in ("step", "kpi", "ring", "flow", "timeline", "table", "chart")
                                                       or n.get("marker") == "num"):
                numbered = True
                break
        if numbered:
            continue
        boxes.sort(key=lambda b: (round(b[1] / 20), b[0]))
        for i, (x, y, w, h) in enumerate(boxes):
            px = int(max(56, min(h * 0.42, 132)))
            if st == "block":
                k = i % 3
                base = [pal["primary"], pal["dark"], pal.get("secondary_text") or pal["primary"]][k]
                col = mix("FFFFFF", base, 0.84)
            else:
                col = mix(pal["primary"], pal.get(_WM_STYLES[st]) or _WM_STYLES[st], 0.9)
            slide.add_text("%02d" % (i + 1), x=IN(x + w - px * 1.6 - 14), y=IN(y + 6), w=IN(px * 1.6), h=IN(px * 1.1),
                           fontSize=px / 2.0, color=col, bold=True, fontFace=PR.K.LATIN or PR.K.FONT, align="right",
                           valign="top", margin=0, lineSpacingMultiple=1.0)


def _seq_arrows(slide, res, pal):
    """顺序卡片之间：骑缝的小圆 + 箭头，表示先后衔接"""
    from .blocks import IN
    for boxes in res.get("seq") or []:
        for a, b in zip(boxes, boxes[1:]):
            gx = (a[0] + a[2] + b[0]) / 2
            cy = a[1] + min(a[3], 220) * 0.5
            d = 46
            slide.add_shape("ellipse", x=IN(gx - d / 2), y=IN(cy - d / 2), w=IN(d), h=IN(d), fill={"color": pal["primary"]},
                            line={"color": "FFFFFF", "width": 3})
            slide.add_shape("chevron", x=IN(gx - 7), y=IN(cy - 9), w=IN(16), h=IN(18), fill={"color": "FFFFFF"},
                            line={"type": "none"}, adj={"adj": 50000})


# ── 主流程 ───────────────────────────────────────────

def _engine_page(slide, kit, page, variant, page_no, kicker, brand=None):
    """按 底层引擎 原逻辑画一页 → 新页码（有 AI 模板时，封面/章节/目录/封底/Banner 换成 AI 模板的）"""
    ptype = page.type
    if brand is not None:
        if ptype == "cover":
            brand.draw_cover(slide, page)
            return page_no
        if ptype == "end":
            brand.draw_end(slide, page)
            return page_no
        if ptype == "chapter":
            brand.draw_chapter(slide, page)
            return page_no
        if ptype == "toc":
            brand.draw_toc(slide, page)
            return page_no + 1
    if variant != "default" and RV.render_variant(slide, kit, page, variant, page_no + 1, page.kicker or kicker):
        return page_no + 1
    if ptype == "cover":
        PR.add_cover(slide, page)
    elif ptype == "chapter":
        PR.add_chapter(slide, page)
    elif ptype == "end":
        PR.add_end(slide, page)
    elif ptype == "toc":
        page_no += 1
        PR.add_header(slide, page.title or "目录")
        PR.add_toc(slide, page)
    else:
        fn = PR._PAGE_FNS.get(ptype)
        if fn is None:
            page = PR.coerce_to_bullets(page)
            fn = PR.add_bullets
        page_no += 1
        (brand.draw_header if brand else PR.add_header)(slide, page.title or "未命名")
        fn(slide, page)
        PR.add_footer(slide, page.note, page_no)
    return page_no


def build_brand_layouts(pres, brand):
    """AI 模板的母版版式：封面 / 标题和内容 / 章节页 / 封底，按同一套画法生成"""
    from .engine.layouts import PROMPT
    out = {}
    for key, name, ltype, ph, fn in (("cover", "封面", "title", "ctrTitle", lambda c: brand.draw_cover(c, {"title": PROMPT["title"]})),
                                     ("content", "标题和内容", "obj", "title", lambda c: brand.draw_header(c, PROMPT["title"])),
                                     ("chapter", "章节页", "secHead", "title", lambda c: brand.draw_chapter(c, {"part": 1, "title": PROMPT["title"]})),
                                     ("end", "封底", "titleOnly", "title", lambda c: brand.draw_end(c, {"title": "谢谢"}))):
        n, c = pres.add_layout(name, ltype, ph)
        c.background = "FFFFFF"
        fn(c)
        out[key] = n
    return out


def _pre(pages):
    """取出 layout，free 页先转成要点页让 底层引擎 规范化/校验能过"""
    lays, raw = [], []
    for p in pages:
        p = dict(p)
        lay = p.pop("layout", None)
        lays.append(lay)
        if p.get("type") == "free":
            flat = flatten_to_page(lay or {}, p.get("title"))
            p["type"] = "bullets"
            p["items"] = flat["items"] or [{"text": p.get("title") or "（空）"}]
            p["_free"] = True
        raw.append(p)
    return raw, lays


def render_deck(pages, template=None, title=None, options=None, brand=None):
    """brand：AI 模板设计（dict，见 brand.py）；给了就不用现成模板，整套模板由程序按它画"""
    from . import tokens
    from .brand import Brand
    options = dict(options or {})
    raw, lays = _pre(pages)
    doc_pages, errors = PA.prepare({"pages": raw})
    if errors:
        raise PA.DeckError(errors)
    if len(doc_pages) != len(lays):
        lays = [None] * len(doc_pages)
    for p, lay, r in zip(doc_pages, lays, raw):
        if lay:
            p["layout"] = lay
        if r.get("_free"):
            p["type"] = "free"
    bobj = None
    if brand is None and not isinstance(template, dict):
        # 没选模板：用推荐的第 1 套系统模板（和 pick 给用户看的第 1 套一致）
        from .pick import recommend
        r = recommend(json.dumps({"title": title, "pages": pages}, ensure_ascii=False)[:4000])[0]
        brand = {"cover": r["cover"], "palette": r["palette"]}
    if brand is not None:
        deck_title = title or next((p.get("title") for p in doc_pages if p.get("type") == "cover"), "") or ""
        bobj = Brand(brand, deck_title, options.get("baseDir"))
        theme = bobj.theme()
    else:
        theme = template if isinstance(template, dict) else PA.load_template(template, options.get("templateDirs"))
    cn, latin, warns = PA.font_report(theme, options.get("fonts"))
    title = title or next((p.get("title") for p in doc_pages if p.get("type") == "cover"), None) or "演示文稿"
    pres = Presentation(PR.PAGE_W / 144.0, PR.PAGE_H / 144.0, title=title, theme_colors=theme.get("colors"), font=cn,
                        font_hei=(theme.get("fonts") or {}).get("hei") or theme.get("fontHei") or "黑体")
    pres.autofit = True

    pages_ad = PR.ad(copy.deepcopy(doc_pages))
    PR.apply_theme(theme, options.get("fonts"))
    PR.K.show_footer = not options.get("noPageFooter")
    PR.K.base_dir = options.get("baseDir")
    PR.K.icons_on = True
    measure.set_fonts(PR.K.FONT, PR.K.LATIN)
    if PR.K.LATIN:
        pres.latin_fonts[PR.K.FONT] = PR.K.LATIN
        pres.latin_fonts[PR.K.FONT_HEI] = PR.K.LATIN
    # 底层引擎 的版式选择（只在交给它画的页上用）；free 页按要点页参与节奏
    vpages = [dict(p, type="bullets") if p.get("type") == "free" else p for p in pages_ad]
    variants = resolve_variants(vpages)
    if bobj:
        PR.K.CHART_COLORS = list(bobj.pal["chart"])
        PR.K.ACCENTS = [bobj.pal["primary"], bobj.pal["secondary"], bobj.pal["secondary_text"], bobj.pal["accent_text"]]
    kit = RV.Kit(PR.C, PR.K.FONT, PR.K.LATIN, PR.brand_locked(theme), None, PR.K.show_footer,
                 bobj.draw_header if bobj else PR.add_header,
                 PR.add_footer, PR.add_chart, PR.resolve_image_file, PR.icon_badge, True)
    layout_of = build_brand_layouts(pres, bobj) if bobj else PR.build_layouts(pres)
    pres.show_master_sp = False
    pal = dict(bobj.pal) if bobj else palette(PR.C)
    saved_area = dict(tokens.AREA)
    if bobj:
        tokens.AREA.update(bobj.area)
        STY.use(bobj.lang)
        if STY.CUR.get("area"):
            tokens.AREA.update(STY.CUR["area"])
    else:
        STY.use("corporate")
    mode = str(options.get("design", "auto"))  # auto | off（off = 完全用 底层引擎，做对照）

    page_no = 0
    kicker = None
    prev_sig = None
    fam_hist = []
    report = []
    for pi, page in enumerate(pages_ad):
        slide = pres.add_slide()
        slide.background = "FFFFFF"
        kind = page.type if page.type in ("cover", "chapter", "end") else "content"
        slide.set_layout(layout_of[kind])
        slide.title_ph = "ctrTitle" if page.type == "cover" else "title"
        PR.K.page_icons = set()
        if page.type == "chapter":
            kicker = ("%s · %s" % (page.partText or "PART %s" % (page.part or ""), page.title or "")).strip()
        variant = variants[pi]
        entry = {"page": pi + 1, "type": page.type, "title": page.title or ""}
        explicit = bool(page.get("variant")) and not page.get("layout")
        lab_ok = (mode != "off" and page.type not in ("cover", "chapter", "end", "toc") and not explicit
                  and (variant not in ({"annotated"} if bobj is not None else STRONG_VARIANTS | SEMANTIC_VARIANTS)
                       or page.get("layout")))
        if bobj is not None and page.type not in ("cover", "chapter", "end", "toc"):
            bobj.page_bg(slide)
        got = design_page(page, prev_sig, fam_hist) if lab_ok else None
        if got and got[1] is not None:
            src, tree, res, notes = got
            page_no += 1
            (bobj.draw_header if bobj else PR.add_header)(slide, page.title or "未命名")
            page_warns = []
            draw_tree(slide, res, pal, page_warns)
            PR.add_footer(slide, page.note, page_no)
            prev_sig = signature(tree)
            fam_hist.append(family(tree))
            entry.update(source=src, level=res["report"]["level"], fill=res["report"]["fill"],
                         warnings=[m for _, m in res["report"]["warnings"]] + page_warns, notes=notes)
        else:
            if page.type == "free":
                page = PR.ad(flatten_to_page(page.get("layout") or {}, page.title))
            page_no = _engine_page(slide, kit, page, variant, page_no, kicker, bobj)
            prev_sig = None
            fam_hist.append("engine")
            entry.update(source="旧版式:" + VARIANT_LABELS.get(variant, variant),
                         notes=(got[3] if got else []))
        report.append(entry)
    tokens.AREA.clear()
    tokens.AREA.update(saved_area)
    STY.use("corporate")
    data = pres.to_bytes()
    info = {"title": title, "pages": report, "warnings": warns + list(PR.K.warnings) + list(pres.warnings)}
    if bobj:
        info["brand"] = bobj.notes
    return data, info


def render_deck_file(in_path, out_path, template=None, options=None):
    with open(in_path, encoding="utf-8-sig") as f:
        doc = PA.parse_deck_text(f.read())
    options = dict(options or {})
    options.setdefault("baseDir", os.path.dirname(os.path.abspath(in_path)))
    data, info = render_deck(doc.get("pages") or [], template or doc.get("template"), doc.get("title"), options,
                             brand=options.pop("brand", None) or doc.get("brand"))
    d = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(out_path, "wb") as f:
        f.write(data)
    info["output"] = os.path.abspath(out_path)
    return info
