"""AI 设计整套模板：AI 只回答几个选择题，程序画出封面、目录、章节页、封底和内容页 Banner。

deck.json 顶层写 "brand"（全部可省，省了程序按气质/标题自己定）：
  {"org": "零售金融部", "mood": "稳重 金融", "palette": 色板id, "primary": "主色hex",
   "cover": "diagonal|split|arcs|band|frame|mosaic", "pattern": "dots|lines|waves|hex|grid|none",
   "banner": "bar|line|tab", "logo": "logo 图片路径", "image": "封面照片路径", "motif": "装饰图标 id"}

素材全部离线获得：
  · 渐变、几何块、圆环、底纹（点阵/斜线/波浪/六边形/网格）—— 程序用原生矢量形状画，PowerPoint 里可编辑、放大不糊
  · 装饰图标 —— 209 个内置矢量图标，按标题关键词自动挑
  · logo / 照片 —— 用户给的文件；没有 logo 时自动生成「文字标志」（首字方印 + 单位名）
"""
import math
import os

from .engine.ooxml.geom import Path
from .engine import icons as ICONS
from .engine.render_variants import clipped_ring, clipped_disc

from . import measure as M
from .palette import build as build_palette, mix

W, H = 1920, 1080
COVERS = ("diagonal", "split", "arcs", "band", "frame", "mosaic")
PATTERNS = ("dots", "lines", "waves", "hex", "grid", "none")
BANNERS = ("bar", "line", "tab")
COVER_BANNER = {"diagonal": "bar", "split": "tab", "arcs": "line", "band": "bar", "frame": "line", "mosaic": "tab"}
COVER_PATTERN = {"diagonal": "dots", "split": "lines", "arcs": "none", "band": "waves", "frame": "hex", "mosaic": "grid"}
CHAPTER_DARK = {"diagonal", "frame", "band"}
MOOD_COVER = [("金融 银行 稳重 年报 正式", "diagonal"), ("科技 数字 AI 互联网 创新", "mosaic"),
              ("政务 党建 国企 红色", "band"), ("高端 奢华 私行 财富", "frame"),
              ("咨询 研究 分析 简约 极简", "arcs"), ("营销 活力 推介 活动 零售", "split")]


def IN(px):
    return px / 144.0


def P(px):
    return px / 2.0


class Brand:
    def __init__(self, spec, deck_title="", base_dir=None):
        spec = dict(spec or {})
        self.notes = []
        self.base_dir = base_dir
        self.pal, pn = build_palette(spec)
        self.notes += pn
        mood = str(spec.get("mood") or "")
        cover = spec.get("cover")
        if cover not in COVERS:
            if cover:
                self.notes.append("封面构图 %r 不在可选范围，按气质选" % cover)
            cover = next((c for words, c in MOOD_COVER if any(w in mood for w in words.split())), None)
            if cover is None:  # 没有气质：按标题确定性地挑一个（同一标题每次一样）
                cover = COVERS[sum(ord(ch) for ch in str(deck_title)) % len(COVERS)]
        self.cover = cover
        pat = spec.get("pattern")
        if pat not in PATTERNS:
            if pat:
                self.notes.append("底纹 %r 不在可选范围，用默认" % pat)
            pat = COVER_PATTERN[cover]
        self.pattern = pat
        ban = spec.get("banner")
        self.banner = ban if ban in BANNERS else COVER_BANNER[cover]
        from .styles import LANGS, COVER_LANG
        st = spec.get("style")
        if st and st not in LANGS:
            self.notes.append("设计语言 %r 不在可选范围，按封面配套" % st)
        self.lang = st if st in LANGS else COVER_LANG[cover]
        self.org = str(spec.get("org") or "").strip()
        self.logo = self._file(spec.get("logo"), "logo")
        self.image = self._file(spec.get("image"), "封面照片")
        mot = spec.get("motif")
        self.motif = mot if mot in ICONS.icons() else ICONS.auto_pick(deck_title)
        # 字体：默认用最常见的「微软雅黑」（Mac / WPS 打开时会自动换成系统里的同类黑体），中西文同一种字体；
        # 用户在 brand 里写了 font / latin 就用用户的
        self.font = str(spec.get("font") or "微软雅黑")
        self.latin = spec.get("latin") or None
        self.area = {"bar": dict(x=96, y=180, w=1728, h=816), "line": dict(x=96, y=196, w=1728, h=800),
                     "tab": dict(x=96, y=184, w=1728, h=812)}[self.banner]
        self.notes.append("封面 %s · 设计语言 %s · 底纹 %s · Banner %s · 装饰图标 %s%s" % (
            cover, LANGS[self.lang]["name"], pat, self.banner, self.motif, "" if self.logo else " · 文字标志"))

    def _file(self, rel, what):
        if not rel:
            return None
        cands = [rel] if os.path.isabs(rel) else [os.path.join(self.base_dir or os.getcwd(), rel), rel]
        for c in cands:
            if os.path.isfile(c):
                return c
        self.notes.append("%s文件找不到：%s（已改用程序生成的素材）" % (what, rel))
        return None

    def theme(self, name="AI 设计模板"):
        from .palette import to_engine_colors
        return {"id": "lab-brand", "name": name, "colors": to_engine_colors(self.pal), "style": "generic",
                "fonts": {"cn": self.font, "hei": self.font, "latin": self.latin}, "assets": {}}

    # ════════════ 基础画法 ════════════
    def rect(self, s, x, y, w, h, fill, line=None, shape="rect", **o):
        f = fill if isinstance(fill, dict) else {"color": fill}
        o = {k: v for k, v in o.items() if v is not None}
        s.add_shape(shape, x=IN(x), y=IN(y), w=IN(w), h=IN(h), fill=f, line=line or {"type": "none"}, **o)

    def grad(self, a, b, ang=45):
        return {"type": "grad", "ang": ang, "stops": [{"pos": 0, "color": a}, {"pos": 100, "color": b}]}

    def text(self, s, t, x, y, w, h, px, color, bold=False, align="left", valign="top", lh=1.15, spacing=None,
             font=None, alpha=0):
        o = dict(x=IN(x), y=IN(y), w=IN(w), h=IN(h), fontSize=P(px), color=color, bold=bold, fontFace=font or self.font,
                 align=align, valign=valign, margin=0, lineSpacingMultiple=lh)
        if spacing:
            o["charSpacing"] = spacing
        if alpha:
            o["transparency"] = alpha
        s.add_text(t, **o)

    def fit(self, t, w, mx, mn, max_lines=2):
        px = mx
        while px > mn and M.lines(t, w, px, True) > max_lines:
            px -= 4
        return px

    def icon(self, s, iid, x, y, size, color, alpha=0):
        got = ICONS.icon_path(iid)
        if not got:
            return
        p, (ox, oy, vw, vh), filled = got
        sc = size / max(vw, vh)
        dw, dh = vw * sc, vh * sc
        o = dict(local=(ox, oy, vw, vh), x=IN(x + (size - dw) / 2), y=IN(y + (size - dh) / 2), w=IN(dw), h=IN(dh))
        if filled:
            s.add_custom(p, fill={"color": color, "transparency": alpha}, line={"type": "none"}, **o)
        else:
            s.add_custom(p, fill={"type": "none"}, line={"color": color, "width": max(1, size / 24.0), "transparency": alpha},
                         **o)

    # ── 底纹（整块一个矢量形状） ──
    def pattern_fill(self, s, x, y, w, h, color, alpha, kind=None):
        kind = kind or self.pattern
        p = Path()
        stroke = True
        if kind == "dots":
            stroke = False
            step, r = 34, 2.6
            for j in range(int(h // step) + 1):
                for i in range(int(w // step) + 1):
                    cx, cy = x + i * step + (step / 2 if j % 2 else 0) + 6, y + j * step + 6
                    if cx + r <= x + w and cy + r <= y + h:
                        p.arc(cx, cy, r, r, 0, 360, connect=False)
                        p.close()
        elif kind == "lines":
            step = 26
            for k in range(-int(h // step) - 1, int(w // step) + 1):
                x0, y0 = x + k * step, y + h
                x1, y1 = x0 + h, y
                # 斜线裁剪到矩形
                if x0 < x:
                    y0 -= (x - x0)
                    x0 = x
                if x1 > x + w:
                    y1 += (x1 - (x + w))
                    x1 = x + w
                if x1 > x0 and y0 > y1:
                    p.move(x0, y0).line(x1, y1)
        elif kind == "waves":
            n = 9
            for k in range(n):
                yy = y + h * (k + 0.5) / n
                amp = h / n * 0.32
                seg = w / 4.0
                p.move(x, yy)
                for q in range(4):
                    sx = x + q * seg
                    sg = 1 if q % 2 == 0 else -1
                    p.cubic(sx + seg * 0.33, yy - amp * sg, sx + seg * 0.66, yy - amp * sg, sx + seg, yy)
        elif kind == "hex":
            r = 30
            dx, dy = r * math.sqrt(3), r * 1.5
            for j in range(int(h // dy) + 2):
                for i in range(int(w // dx) + 2):
                    cx = x + i * dx + (dx / 2 if j % 2 else 0)
                    cy = y + j * dy
                    pts = [(cx + r * math.cos(math.radians(60 * a + 30)), cy + r * math.sin(math.radians(60 * a + 30)))
                           for a in range(6)]
                    if all(x <= px_ <= x + w and y <= py_ <= y + h for px_, py_ in pts):
                        p.polygon(pts)
        elif kind == "grid":
            step = 48
            for i in range(1, int(w // step) + 1):
                p.move(x + i * step, y).line(x + i * step, y + h)
            for j in range(1, int(h // step) + 1):
                p.move(x, y + j * step).line(x + w, y + j * step)
        else:
            return
        if p.empty():
            return
        bx0, by0, bx1, by1 = p.bbox()
        o = dict(local=(bx0, by0, max(1, bx1 - bx0), max(1, by1 - by0)), x=IN(bx0), y=IN(by0),
                 w=IN(max(1, bx1 - bx0)), h=IN(max(1, by1 - by0)), name="Pattern " + kind)
        if stroke:
            s.add_custom(p, fill={"type": "none"}, line={"color": color, "width": 0.75, "transparency": alpha * 100}, **o)
        else:
            s.add_custom(p, fill={"color": color, "transparency": alpha * 100}, line={"type": "none"}, **o)

    # ── 标志 ──
    def mark(self, s, x, y, size, on_dark, with_name=True, align="left"):
        """logo 文件优先；没有就画文字标志：首字方印 + 单位名"""
        if self.logo:
            s.add_image(path=self.logo, x=IN(x), y=IN(y), w=IN(size * 3.2), h=IN(size), sizing={"type": "contain"})
            return
        if not self.org:
            return  # 没有 logo 也没有单位名：不画标志（不编造）
        name = self.org
        ch = name[0]
        bg = "FFFFFF" if on_dark else self.pal["primary"]
        fg = self.pal["primary"] if on_dark else "FFFFFF"
        nw = M.text_w(name, size * 0.42, True) + 8 if with_name else 0
        if align == "right":
            x = x - size - (nw + size * 0.3 if with_name else 0)
        s.add_text(ch, shape="roundRect", rectRadius=IN(size * 0.18), x=IN(x), y=IN(y), w=IN(size), h=IN(size),
                   fill={"color": bg}, line={"type": "none"}, fontSize=P(size * 0.56), bold=True, color=fg,
                   fontFace=self.font, align="center", valign="middle", margin=0, noFit=True)
        if with_name:
            self.text(s, name, x + size * 1.3, y, nw + 40, size, size * 0.42, "FFFFFF" if on_dark else self.pal["ink"],
                      bold=True, valign="middle", lh=1.0)

    # ════════════ 封面 ════════════
    def _cover_text(self, s, page, x, y, w, on_dark, align="left", big=96):
        pal = self.pal
        title = str(page.get("title") or "")
        px = self.fit(title, w, big, 56, 2)
        n = M.lines(title, w, px, True)
        th = n * px * 1.2 * 1.12
        col = "FFFFFF" if on_dark else pal["ink"]
        bar_x = x if align == "left" else x + w / 2 - 40
        self.rect(s, bar_x, y - 44, 80, 8, pal["accent"])
        self.text(s, title, x, y, w, th + 10, px, col, bold=True, align=align, lh=1.12)
        cy = y + th + 28
        sub = str(page.get("subtitle") or "")
        if sub:
            sp = self.fit(sub, w, 40, 28, 2)
            self.text(s, sub, x, cy, w, sp * 2.8, sp, mix(col, pal["dark"] if on_dark else "FFFFFF", 0.15) if on_dark
                      else pal["secondary_text"], align=align, lh=1.25)
            cy += M.lines(sub, w, sp) * sp * 1.5 + 18
        meta = str(page.get("meta") or "")
        if meta:
            self.text(s, meta, x, cy + 10, w, 44, 26, mix(col, pal["dark"], 0.3) if on_dark else pal["muted"],
                      align=align, lh=1.0, spacing=1)

    def draw_cover(self, s, page, end=False):
        pal = self.pal
        c = self.cover
        ttl = page if not end else dict(title=page.get("title") or "谢谢", subtitle=page.get("subtitle") or "THANK YOU",
                                       meta=self.org)
        if c == "diagonal":
            self.rect(s, 0, 0, W, H, self.grad(pal["dark"], pal["primary"], 30))
            pg = Path().polygon([(1100, 0), (W, 0), (W, H), (720, H)])
            s.add_custom(pg, x=IN(720), y=0, w=IN(W - 720), h=IN(H), fill={"color": pal["secondary"], "transparency": 78},
                         line={"type": "none"})
            pg2 = Path().polygon([(1420, 0), (W, 0), (W, H), (1180, H)])
            s.add_custom(pg2, x=IN(1180), y=0, w=IN(W - 1180), h=IN(H), fill={"color": pal["secondary"], "transparency": 70},
                         line={"type": "none"})
            self.pattern_fill(s, 1240, 80, 600, 560, "FFFFFF", 0.82)
            self.icon(s, self.motif, 1380, 560, 400, "FFFFFF", 86)
            self._cover_text(s, ttl, 140, 400, 1000, True)
            self.mark(s, 140, 920, 64, True)
        elif c == "split":
            pw = 880
            self.rect(s, 0, 0, pw, H, self.grad(pal["primary"], pal["dark"], 70))
            if self.image:
                s.add_image(path=self.image, x=IN(pw), y=0, w=IN(W - pw), h=IN(H), sizing={"type": "cover"})
                self.rect(s, pw, 0, W - pw, H, {"color": pal["dark"], "transparency": 82})
            else:
                self.rect(s, pw, 0, W - pw, H, pal["soft"])
                box = (pw, 0, W, H)
                clipped_disc(s, 1500, 560, 360, box, pal["secondary"], 0.9)
                clipped_disc(s, 1760, 300, 200, box, pal["accent"], 0.85)
                clipped_ring(s, 1500, 560, 450, box, pal["primary"], 0.5, 3)
                clipped_ring(s, 1500, 560, 530, box, pal["primary"], 0.25, 2)
                self.icon(s, self.motif, 1380, 440, 240, "FFFFFF")
                self.pattern_fill(s, pw + 60, 760, 420, 260, pal["primary"], 0.6)
            self.pattern_fill(s, 0, 0, pw, 220, "FFFFFF", 0.88)
            self._cover_text(s, ttl, 110, 420, pw - 200, True, big=84)
            self.mark(s, 110, 930, 60, True)
        elif c == "arcs":
            self.rect(s, 0, 0, W, H, "FFFFFF")
            box = (0, 0, W, H)
            for i, (r, a) in enumerate(((880, 0.10), (720, 0.16), (560, 0.24))):
                clipped_ring(s, 1780, 1040, r, box, pal["primary"], a * 2.2, 2)
            clipped_disc(s, 1780, 1040, 420, box, pal["primary"], 1.0)
            clipped_disc(s, 1780, 1040, 300, box, pal["secondary"], 1.0)
            clipped_disc(s, 1500, 380, 70, box, pal["accent"], 1.0)
            self.icon(s, self.motif, 1600, 820, 170, "FFFFFF")
            self.rect(s, 0, 0, 24, H, pal["primary"])
            self._cover_text(s, ttl, 150, 400, 1050, False)
            self.mark(s, 150, 930, 60, False)
        elif c == "band":
            self.rect(s, 0, 0, W, H, "FFFFFF")
            by = 690
            self.rect(s, 0, by, W, H - by, self.grad(pal["primary"], pal["dark"], 0))
            self.pattern_fill(s, 0, by, W, H - by, "FFFFFF", 0.85)
            self.rect(s, 0, by - 10, 520, 10, pal["accent"])
            self.icon(s, self.motif, 1560, 250, 260, pal["primary"], 85)
            self._cover_text(s, dict(ttl, meta=None), 150, 300, 1250, False)
            if ttl.get("meta"):
                self.text(s, ttl["meta"], 150, by + 90, 1100, 44, 30, "FFFFFF", lh=1.0, spacing=1)
            self.mark(s, 1820, by + 260, 60, True, align="right")
        elif c == "frame":
            self.rect(s, 0, 0, W, H, self.grad(pal["dark"], mix(pal["dark"], pal["primary"], 0.45), 120))
            self.pattern_fill(s, 0, 0, W, H, "FFFFFF", 0.93)
            self.rect(s, 60, 60, W - 120, H - 120, {"type": "none"}, line={"color": pal["accent"], "width": 1.5})
            for cx, cy in ((60, 60), (W - 60, 60), (60, H - 60), (W - 60, H - 60)):
                s.add_shape("diamond", x=IN(cx - 12), y=IN(cy - 12), w=IN(24), h=IN(24), fill={"color": pal["accent"]},
                            line={"type": "none"})
            self.icon(s, self.motif, W / 2 - 50, 230, 100, pal["accent"])
            self._cover_text(s, ttl, 260, 470, W - 520, True, align="center")
            self.mark(s, W / 2 - 40, 900, 56, True, with_name=False)
            if self.org:
                self.text(s, self.org, 0, 970, W, 40, 24, mix("FFFFFF", pal["dark"], 0.3), align="center", lh=1.0)
        else:  # mosaic
            self.rect(s, 0, 0, W, H, "FFFFFF")
            x0, cols, rows, gap = 1000, 4, 4, 14
            tw = (W - 80 - x0 - gap * (cols - 1)) / cols
            th = (H - 160 - gap * (rows - 1)) / rows
            picks = self._mosaic_icons(page.get("title"), cols * rows)
            nic = 0
            for j in range(rows):
                for i in range(cols):
                    k = j * cols + i
                    style = (i * 7 + j * 3) % 6
                    fill = [pal["primary"], pal["soft"], pal["secondary"], pal["soft"], pal["dark"], pal["soft"]][style]
                    if (i, j) == (2, 1):
                        fill = pal["accent"]
                    tx, ty = x0 + i * (tw + gap), 80 + j * (th + gap)
                    self.rect(s, tx, ty, tw, th, fill)
                    if style in (0, 2, 4) and picks:
                        ic = picks[nic % len(picks)]
                        nic += 1
                        self.icon(s, ic, tx + tw / 2 - 40, ty + th / 2 - 40, 80, "FFFFFF")
                    elif style in (1, 3, 5) and k % 3 == 0:
                        self.pattern_fill(s, tx + 16, ty + 16, tw - 32, th - 32, pal["primary"], 0.65, "dots")
            self._cover_text(s, ttl, 130, 420, 800, False, big=84)
            self.mark(s, 130, 930, 60, False)

    def _mosaic_icons(self, title, n):
        used = set()
        out = [self.motif]
        used.add(self.motif)
        t = str(title or "")
        for _ in range(4):
            iid = ICONS.auto_pick(t, used)
            if iid in used:
                break
            used.add(iid)
            out.append(iid)
        for g in ("fa-chart-line", "fa-users", "fa-bullseye", "fa-lightbulb", "fa-shield-halved", "fa-handshake",
                  "fa-rocket", "fa-coins"):
            if len(out) >= 6:
                break
            if g not in used:
                out.append(g)
        return out

    def draw_end(self, s, page):
        self.draw_cover(s, page, end=True)

    # ════════════ 章节页 ════════════
    def draw_chapter(self, s, page):
        pal = self.pal
        part = page.get("part")
        num = "%02d" % int(part) if str(part or "").isdigit() else str(part or "")
        title = str(page.get("title") or "")
        if self.cover in CHAPTER_DARK:
            self.rect(s, 0, 0, W, H, self.grad(pal["dark"], pal["primary"], 30))
            self.pattern_fill(s, 1100, 0, 820, H, "FFFFFF", 0.88)
            self.text(s, num, 120, 180, 900, 520, 440, "FFFFFF", bold=True, font=self.latin, lh=1.0, alpha=86)
            self.rect(s, 160, 640, 80, 8, pal["accent"])
            self.text(s, "PART " + num, 160, 680, 600, 44, 30, mix("FFFFFF", pal["dark"], 0.25), bold=True,
                      font=self.latin, spacing=4, lh=1.0)
            px = self.fit(title, 1300, 96, 56, 2)
            self.text(s, title, 160, 740, 1500, px * 2.8, px, "FFFFFF", bold=True, lh=1.12)
        else:
            self.rect(s, 0, 0, W, H, "FFFFFF")
            self.rect(s, 0, 0, 640, H, self.grad(pal["primary"], pal["dark"], 60))
            self.pattern_fill(s, 0, H - 380, 640, 380, "FFFFFF", 0.86)
            self.text(s, num, 0, 330, 640, 360, 300, "FFFFFF", bold=True, font=self.latin, align="center", lh=1.0)
            self.text(s, "PART " + num, 780, 420, 600, 44, 30, pal["secondary_text"], bold=True, font=self.latin,
                      spacing=4, lh=1.0)
            px = self.fit(title, 1000, 96, 56, 2)
            self.text(s, title, 780, 480, 1040, px * 2.8, px, pal["ink"], bold=True, lh=1.12)
            self.rect(s, 780, 480 + M.lines(title, 1000, px, True) * px * 1.35 + 30, 80, 8, pal["accent"])
            self.icon(s, self.motif, 1640, 820, 180, pal["primary"], 88)

    # ════════════ 目录 ════════════
    def draw_toc(self, s, page):
        from .styles import LANGS
        pal = self.pal
        kind = LANGS[self.lang].get("toc") or "tiles"
        self.page_bg(s)
        self.draw_header(s, page.get("title") or "目录")
        items = []
        for it in page.get("items") or []:
            t = it.get("text") if isinstance(it, dict) else it
            if t:
                items.append(str(t))
        if not items:
            return
        a = self.area
        n = len(items)
        split = [(t.partition("：")[0], t.partition("：")[2]) for t in items]
        if kind in ("cards", "blocks") and n <= 6:
            cols = n if n <= 4 else 3
            rows = (n + cols - 1) // cols
            gap = 28
            cw = (a["w"] - gap * (cols - 1)) / cols
            ch = min(360, (a["h"] - gap * (rows - 1)) / rows)
            y0 = a["y"] + (a["h"] - ch * rows - gap * (rows - 1)) / 2
            for i, (head, desc) in enumerate(split):
                r, c = divmod(i, cols)
                x, y = a["x"] + c * (cw + gap), y0 + r * (ch + gap)
                if kind == "blocks":
                    fill = [pal["primary"], pal["dark"], pal["secondary_text"]][i % 3]
                    self.rect(s, x, y, cw, ch, fill)
                    fg, sub = "FFFFFF", mix("FFFFFF", fill, 0.25)
                else:
                    self.rect(s, x, y, cw, ch, "FFFFFF", shape="roundRect" if self.lang == "rounded" else "rect",
                              rectRadius=IN(26) if self.lang == "rounded" else None,
                              shadow={"type": "outer", "color": pal["dark"], "blur": 18, "offset": 4, "angle": 90,
                                      "opacity": 0.10} if self.lang == "rounded" else None)
                    if self.lang == "tech":
                        self.rect(s, x, y, cw, 6, pal["secondary"])
                    fg, sub = pal["ink"], pal["muted"]
                self.text(s, "%02d" % (i + 1), x + 40, y + 36, cw - 80, 110, 96,
                          fg if kind == "blocks" else pal["primary"], bold=True, font=self.latin, lh=1.0)
                hp = self.fit(head, cw - 80, 44, 30, 2)
                self.text(s, head, x + 40, y + ch - 60 - hp * 2.6 - (30 if desc else 0), cw - 80, hp * 2.6, hp, fg,
                          bold=True, valign="bottom", lh=1.2)
                if desc:
                    self.text(s, desc, x + 40, y + ch - 76, cw - 80, 40, 24, sub, lh=1.0)
            return
        if kind in ("numbers", "center"):
            per = n
            rh = min(170, a["h"] / per)
            y0 = a["y"] + (a["h"] - rh * per) / 2
            center = kind == "center"
            for i, (head, desc) in enumerate(split):
                y = y0 + i * rh
                if center:
                    self.text(s, "%02d" % (i + 1), a["x"], y + 6, a["w"], 40, 30, pal["accent_text"], bold=True,
                              font=self.latin, align="center", lh=1.0, spacing=4)
                    self.text(s, head + ("　·　" + desc if desc else ""), a["x"], y + 52, a["w"], 60, 44, pal["ink"],
                              bold=True, align="center", lh=1.0)
                    if i < n - 1:
                        s.add_shape("diamond", x=IN(W / 2 - 6), y=IN(y + rh - 10), w=IN(12), h=IN(12),
                                    fill={"color": pal["accent"]}, line={"type": "none"})
                else:
                    self.text(s, "%02d" % (i + 1), a["x"], y, 200, rh, 110, pal["primary"], bold=True, font=self.latin,
                              valign="middle", lh=1.0)
                    self.text(s, head, a["x"] + 240, y + rh / 2 - 52, a["w"] - 240, 60, 48, pal["ink"], bold=True, lh=1.0)
                    if desc:
                        self.text(s, desc, a["x"] + 240, y + rh / 2 + 14, a["w"] - 240, 40, 28, pal["muted"], lh=1.0)
                    self.rect(s, a["x"], y + rh - 1, a["w"], 1.5, pal["ink"] if i < n - 1 else "FFFFFF")
            return
        # tiles（默认）
        cols = 2 if n >= 6 else 1
        per = (n + cols - 1) // cols
        cw = (a["w"] - 80 * (cols - 1)) / cols
        rh = min(200, a["h"] / per)
        y0 = a["y"] + (a["h"] - rh * per) / 2
        for i, (head, desc) in enumerate(split):
            c, r = divmod(i, per)
            x, y = a["x"] + c * (cw + 80), y0 + r * rh
            tile = 128 if rh >= 170 else (104 if rh >= 130 else 84)
            self.rect(s, x, y + (rh - tile) / 2, tile, tile, pal["primary"] if i % 2 == 0 else pal["secondary"])
            self.text(s, "%02d" % (i + 1), x, y + (rh - tile) / 2, tile, tile, tile * 0.44, "FFFFFF", bold=True,
                      font=self.latin, align="center", valign="middle", lh=1.0)
            tx = x + tile + 36
            hp = 48 if cols == 1 else 40
            if desc:
                self.text(s, head, tx, y + rh / 2 - hp - 6, cw - tile - 40, hp * 1.2, hp, pal["ink"], bold=True, lh=1.0)
                self.text(s, desc, tx, y + rh / 2 + 12, cw - tile - 40, 44, 30 if cols == 1 else 26, pal["muted"], lh=1.0)
            else:
                self.text(s, head, tx, y, cw - tile - 40, rh, hp, pal["ink"], bold=True, valign="middle", lh=1.0)
            if r < per - 1:
                self.rect(s, tx, y + rh - 1, cw - tile - 36, 1.5, pal["line"])

    # ════════════ 内容页底色（按设计语言） ════════════
    def page_bg(self, s):
        from .styles import LANGS
        bg = LANGS[self.lang].get("bg")
        top = {"bar": 128, "line": 150, "tab": 158}[self.banner]
        if bg == "tint":
            self.rect(s, 0, top, W, H - top, self.pal["soft2"])
        elif bg == "grid":
            self.pattern_fill(s, 0, top, W, H - top, self.pal["primary"], 0.94, "grid")
        elif bg == "frame":
            self.rect(s, 40, top + 20, W - 80, H - top - 60, {"type": "none"},
                      line={"color": self.pal["accent"], "width": 0.5})

    # ════════════ 内容页 Banner ════════════
    def draw_header(self, s, title):
        pal = self.pal
        title = str(title or "")
        if self.banner == "bar":
            self.rect(s, 0, 0, W, 128, self.grad(pal["primary"], pal["secondary"], 0))
            self.pattern_fill(s, 1380, 0, 540, 128, "FFFFFF", 0.86)
            px = self.fit(title, 1500, 52, 36, 1)
            self.text(s, title, 72, 0, 1560, 128, px, "FFFFFF", bold=True, valign="middle", lh=1.0)
            self.mark(s, 1848, 34, 60, True, with_name=False, align="right")
        elif self.banner == "line":
            px = self.fit(title, 1560, 52, 36, 1)
            self.text(s, title, 96, 44, 1600, 80, px, pal["ink"], bold=True, valign="middle", lh=1.0)
            self.rect(s, 96, 140, W - 192, 1.5, pal["line"])
            self.rect(s, 96, 137, 120, 7, pal["primary"])
            self.mark(s, W - 96, 52, 56, False, with_name=False, align="right")
        else:  # tab
            self.rect(s, 0, 40, 28, 92, pal["primary"])
            self.rect(s, 28, 40, 10, 92, pal["accent"])
            px = self.fit(title, 1500, 52, 36, 1)
            self.text(s, title, 84, 40, 1560, 92, px, pal["ink"], bold=True, valign="middle", lh=1.0)
            self.pattern_fill(s, 1640, 30, 280, 112, pal["primary"], 0.7, "dots" if self.pattern == "none" else self.pattern)
            self.rect(s, 0, 156, W, 1.5, pal["line"])
