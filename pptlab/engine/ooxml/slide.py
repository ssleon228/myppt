"""幻灯片对象：形状 / 文字 / 图片 / 表格 / 图表 / 自由路径。

选项沿用 pptxgenjs 的命名与语义（renderer 从 TS 逐行移植，保持一致）：
  x/y/w/h（英寸）、fontSize（磅）、bold、color、fontFace、align、valign、margin（磅）、
  lineSpacingMultiple、charSpacing（磅）、transparency（0-100）、wrap、fit、paraSpaceAfter、
  fill={color,transparency} | {type:none} | {type:grad,...} | {type:patt,...}、
  line={color,width(磅),dashType,transparency} | {type:none}、rectRadius（英寸）、shadow、rotate、flipH/flipV。
"""
from .util import EMU, emu, esc, pts, hexcolor, color_xml, solid_fill, fnum

TEXT_ALIGN = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}
VALIGN = {"top": "t", "middle": "ctr", "bottom": "b"}

# 形状名（pptxgenjs ShapeType 取值即 OOXML prst）
_PRST_ALIASES = {"line": "line"}


def fill_xml(fill):
    """填充 → XML（None 表示不写填充元素）"""
    if fill is None:
        return None
    if not isinstance(fill, dict):
        return solid_fill(fill)
    t = fill.get("type")
    if t == "none":
        return "<a:noFill/>"
    if t == "grad":
        stops = []
        for s in fill.get("stops", []):
            pos = int(round(max(0.0, min(100.0, float(s.get("pos", 0)))) * 1000))
            stops.append('<a:gs pos="%d">%s</a:gs>' % (pos, color_xml(s.get("color"), alpha=s.get("alpha"))))
        if fill.get("path") == "circle":
            return ('<a:gradFill rotWithShape="1"><a:gsLst>%s</a:gsLst><a:path path="circle">'
                    '<a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path></a:gradFill>' % "".join(stops))
        ang = int(round((float(fill.get("ang", 0)) % 360) * 60000))
        return ('<a:gradFill rotWithShape="1"><a:gsLst>%s</a:gsLst><a:lin ang="%d" scaled="%d"/></a:gradFill>'
                % ("".join(stops), ang, 1 if fill.get("scaled", True) else 0))
    if t == "patt":
        return ('<a:pattFill prst="%s"><a:fgClr>%s</a:fgClr><a:bgClr>%s</a:bgClr></a:pattFill>'
                % (esc(fill.get("prst") or "ltUpDiag"), color_xml(fill.get("fg"), alpha=fill.get("fgAlpha")),
                   color_xml(fill.get("bg"), alpha=fill.get("bgAlpha"))))
    if fill.get("color") is None:
        return None
    return solid_fill(fill.get("color"), fill.get("transparency", 0))


def line_xml(line):
    if line is None:
        return "<a:ln/>"
    if line.get("type") == "none" or (not line.get("color") and not line.get("width")):
        return "<a:ln><a:noFill/></a:ln>"
    w = pts(line.get("width", 1) or 1)
    dash = line.get("dashType") or "solid"
    out = '<a:ln w="%d">%s<a:prstDash val="%s"/>' % (w, solid_fill(line.get("color") or "333333", line.get("transparency", 0)), esc(dash))
    if line.get("cap"):
        out = out.replace('<a:ln w="%d">' % w, '<a:ln w="%d" cap="%s">' % (w, line["cap"]))
    if line.get("join") == "round":
        out += "<a:round/>"
    return out + "</a:ln>"


def shadow_xml(sh):
    if not sh:
        return ""
    blur = pts(sh.get("blur", 8))
    dist = pts(sh.get("offset", 4))
    ang = int(round(float(sh.get("angle", 270)) * 60000))
    op = float(sh.get("opacity", 0.75))
    return ('<a:effectLst><a:outerShdw blurRad="%d" dist="%d" dir="%d" algn="bl" rotWithShape="0">%s</a:outerShdw></a:effectLst>'
            % (blur, dist, ang, color_xml(sh.get("color", "000000"), alpha=op)))


def xfrm_xml(o, tag="a:xfrm"):
    attrs = ""
    rot = o.get("rotate")
    if rot:
        attrs += ' rot="%d"' % int(round((float(rot) % 360) * 60000))
    if o.get("flipH"):
        attrs += ' flipH="1"'
    if o.get("flipV"):
        attrs += ' flipV="1"'
    return '<%s%s><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></%s>' % (
        tag, attrs, emu(o.get("x", 0)), emu(o.get("y", 0)), max(0, emu(o.get("w", 0))), max(0, emu(o.get("h", 0))), tag)


def prst_xml(shape, o):
    shape = shape or "rect"
    av = ""
    if shape == "roundRect" and o.get("rectRadius"):
        cx = max(1, emu(o.get("w", 0)))
        cy = max(1, emu(o.get("h", 0)))
        av = '<a:gd name="adj" fmla="val %d"/>' % int(round(o["rectRadius"] * EMU * 100000 / min(cx, cy)))
    elif o.get("adj"):
        av = "".join('<a:gd name="%s" fmla="val %d"/>' % (k, int(v)) for k, v in o["adj"].items())
    return '<a:prstGeom prst="%s"><a:avLst>%s</a:avLst></a:prstGeom>' % (esc(shape), av)


class Slide:
    def __init__(self, pres, index):
        self.pres = pres
        self.index = index  # 1 基
        self.items = []
        self.rels = []  # (rid, type, target, external)
        self.background = None  # hex
        self.bg_image = None
        self._id = 1
        self.layout_rid = self.add_rel("http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
                                       "../slideLayouts/slideLayout1.xml")
        self.title_shape_id = None
        self.notes = None
        self.layout_no = 1
        self.title_ph = None  # 有自生成版式时：标题文本框标成的占位符类型（title / ctrTitle）

    def set_layout(self, n):
        """挂到第 n 个版式（1 基）"""
        self.layout_no = n
        rid, t, _, ex = self.rels[0]
        self.rels[0] = (rid, t, "../slideLayouts/slideLayout%d.xml" % n, ex)

    # ── 基础设施 ──
    def add_rel(self, rtype, target, external=False):
        for rid, t, tg, ex in self.rels:
            if t == rtype and tg == target:
                return rid
        rid = "rId%d" % (len(self.rels) + 1)
        self.rels.append((rid, rtype, target, external))
        return rid

    def next_id(self):
        self._id += 1
        return self._id

    # ── 形状 ──
    def add_shape(self, shape, **o):
        sid = self.next_id()
        name = "%s %d" % ("Line" if shape == "line" else "Shape", sid)
        fx = fill_xml(o.get("fill"))
        if shape == "line" and fx is None:
            fx = "<a:noFill/>"
        sp = ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
              '<p:spPr>%s%s%s%s%s</p:spPr></p:sp>') % (
            sid, name, xfrm_xml(o), prst_xml(shape, o), fx or "<a:noFill/>" if fx is None else fx,
            line_xml(o.get("line")), shadow_xml(o.get("shadow")))
        self.items.append(sp)
        return sid

    def add_custom(self, path, **o):
        """自由路径形状：path 为局部坐标的 Path；local=(ox,oy,lw,lh) 指定局部坐标框，缺省用路径包围盒。
        x/y/w/h 为在页面上的位置（英寸）。"""
        sid = self.next_id()
        cx = max(1, emu(o.get("w", 0)))
        cy = max(1, emu(o.get("h", 0)))
        local = o.get("local")
        if local is None:
            x0, y0, x1, y1 = path.bbox()
            local = (x0, y0, max(1e-9, x1 - x0), max(1e-9, y1 - y0))
        ox, oy, lw, lh = local
        geom = path.to_custgeom(cx / lw, cy / lh, cx, cy, fill=o.get("fill") not in (None,) and (o.get("fill") or {}).get("type") != "none",
                                stroke=bool(o.get("line")) and o.get("line", {}).get("type") != "none", ox=ox, oy=oy)
        fx = fill_xml(o.get("fill")) or "<a:noFill/>"
        sp = ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
              '<p:spPr>%s%s%s%s%s</p:spPr></p:sp>') % (
            sid, esc(o.get("name") or "Freeform %d" % sid), xfrm_xml(o), geom, fx, line_xml(o.get("line") or {"type": "none"}), shadow_xml(o.get("shadow")))
        self.items.append(sp)
        return sid

    # ── 文字 ──
    def add_text(self, text, **o):
        runs = _normalize_runs(text, o)
        if getattr(self.pres, "autofit", True) and not o.get("noFit"):
            runs, o = self._fit(runs, o)
        sid = self.next_id()
        shape = o.get("shape") or "rect"
        fx = fill_xml(o.get("fill"))
        sp_pr = "%s%s%s%s%s" % (
            xfrm_xml(o), prst_xml(shape, o), fx if fx is not None else "<a:noFill/>",
            line_xml(o.get("line")) if o.get("line") else "<a:ln><a:noFill/></a:ln>", shadow_xml(o.get("shadow")))
        body = _body_pr(o) + "<a:lstStyle/>" + _paragraphs(runs, o, self.pres.latin_fonts)
        name = o.get("name") or "Text %d" % sid
        ph = ""
        if o.get("placeholder"):
            ph = '<p:ph type="%s"/>' % o["placeholder"]
        sp = ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr txBox="1"/><p:nvPr>%s</p:nvPr></p:nvSpPr>'
              '<p:spPr>%s</p:spPr><p:txBody>%s</p:txBody></p:sp>') % (sid, esc(name), ph, sp_pr, body)
        if shape != "rect" or o.get("fill"):
            sp = sp.replace('<p:cNvSpPr txBox="1"/>', "<p:cNvSpPr/>")
        self.items.append(sp)
        return sid

    def _fit(self, runs, o):
        """放不下就整体等比缩字（只缩不放），见 textfit"""
        from .. import textfit
        font = o.get("fontFace") or self.pres.font
        latin = self.pres.latin_fonts.get(font)
        try:
            k = textfit.fit_scale(runs, o, font, latin)
        except Exception:  # noqa: BLE001
            return runs, o
        if k >= 0.995:
            return runs, o

        def sc(v):
            return max(1.0, round(float(v or 18) * k * 2) / 2.0)

        o = dict(o)
        o["fontSize"] = sc(o.get("fontSize"))
        out = []
        for r in runs:
            ro = dict(r.get("options") or {})
            if ro.get("fontSize"):
                ro["fontSize"] = sc(ro["fontSize"])
            out.append({"text": r.get("text"), "options": ro})
        self.pres.fitted = getattr(self.pres, "fitted", 0) + 1
        return out, o

    # ── 图片 ──
    def add_image(self, path=None, data=None, **o):
        media = self.pres.add_media(path=path, data=data)
        if media is None:
            return None
        target, iw, ih = media
        rid = self.add_rel("http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "../media/" + target)
        o = dict(o)
        src_rect = ""
        sizing = o.get("sizing")
        if sizing and iw and ih and o.get("w") and o.get("h"):
            bw, bh = float(o["w"]), float(o["h"])
            ir = iw / float(ih)
            br = bw / bh
            if sizing.get("type") == "contain":
                if ir > br:
                    nh = bw / ir
                    o["y"] = o.get("y", 0) + (bh - nh) / 2
                    o["h"] = nh
                else:
                    nw = bh * ir
                    o["x"] = o.get("x", 0) + (bw - nw) / 2
                    o["w"] = nw
            elif sizing.get("type") == "cover":
                if ir > br:  # 图更宽：左右裁
                    keep = br / ir
                    c = int(round((1 - keep) / 2 * 100000))
                    src_rect = '<a:srcRect l="%d" r="%d"/>' % (c, c)
                else:
                    keep = ir / br
                    c = int(round((1 - keep) / 2 * 100000))
                    src_rect = '<a:srcRect t="%d" b="%d"/>' % (c, c)
        sid = self.next_id()
        geom = o.get("geom") or '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        rws = ' rotWithShape="0"' if o.get("rotWithShape") is False else ' rotWithShape="1"'
        alpha = ""
        if o.get("transparency"):
            alpha = '<a:alphaModFix amt="%d"/>' % int(round((100 - o["transparency"]) * 1000))
        pic = ('<p:pic><p:nvPicPr><p:cNvPr id="%d" name="Picture %d" descr="%s"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
               '<p:blipFill%s><a:blip r:embed="%s">%s</a:blip>%s<a:stretch><a:fillRect/></a:stretch></p:blipFill>'
               '<p:spPr>%s%s%s</p:spPr></p:pic>') % (
            sid, sid, esc(o.get("descr", "")), rws, rid, alpha, src_rect, xfrm_xml(o), geom, line_xml(o["line"]) if o.get("line") else "")
        self.items.append(pic)
        return sid

    # ── 表格 ──
    def add_table(self, rows, **o):
        """rows: [[cell...]...]，cell = str 或 {text, options}；表级选项同 pptxgenjs addTable"""
        sid = self.next_id()
        ncol = max((len(r) for r in rows), default=0)
        if ncol == 0:
            return None
        colw = o.get("colW") or [o.get("w", 1) / ncol] * ncol
        if not isinstance(colw, (list, tuple)):
            colw = [colw] * ncol
        rowh = o.get("rowH")
        if not isinstance(rowh, (list, tuple)):
            rowh = [rowh or 0.4] * len(rows)
        grid = "".join('<a:gridCol w="%d"/>' % emu(c) for c in colw)
        trs = []
        for ri, row in enumerate(rows):
            tcs = []
            for ci in range(ncol):
                cell = row[ci] if ci < len(row) else ""
                if not isinstance(cell, dict):
                    cell = {"text": str(cell), "options": {}}
                co = dict(o)
                for k in ("x", "y", "w", "h", "colW", "rowH", "fill", "line", "shadow", "rectRadius", "shape"):
                    co.pop(k, None)
                co.update(cell.get("options") or {})
                tcs.append(_table_cell(cell.get("text", ""), co, o, self.pres.latin_fonts))
            h = rowh[ri] if ri < len(rowh) else rowh[-1]
            trs.append('<a:tr h="%d">%s</a:tr>' % (emu(h), "".join(tcs)))
        total_h = sum(rowh[:len(rows)]) if rowh else 1
        frame = ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="%d" name="Table %d"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
                 '<p:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></p:xfrm>'
                 '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr/><a:tblGrid>%s</a:tblGrid>%s</a:tbl></a:graphicData></a:graphic></p:graphicFrame>') % (
            sid, sid, emu(o.get("x", 0)), emu(o.get("y", 0)), emu(sum(colw)), emu(total_h), grid, "".join(trs))
        self.items.append(frame)
        return sid

    # ── 图表 ──
    def add_chart_xml(self, chart_part, **o):
        """chart_part: package 里已登记的图表部件文件名（chartN.xml）"""
        rid = self.add_rel("http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart", "../charts/" + chart_part)
        sid = self.next_id()
        frame = ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="%d" name="Chart %d"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
                 '%s<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
                 '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="%s"/></a:graphicData></a:graphic></p:graphicFrame>') % (
            sid, sid, xfrm_xml(o, "p:xfrm"), rid)
        self.items.append(frame)
        return sid

    # ── 输出 ──
    def bg_xml(self):
        if self.background:
            return '<p:bg><p:bgPr>%s<a:effectLst/></p:bgPr></p:bg>' % solid_fill(self.background)
        return ""

    def to_xml(self, show_master_sp=True):
        bg = self.bg_xml()
        attrs = "" if show_master_sp else ' showMasterSp="0"'
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"%s>'
                '<p:cSld>%s<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                '%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>') % (attrs, bg, "".join(self.items))

    def rels_xml(self):
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        for rid, t, tg, ex in self.rels:
            out.append('<Relationship Id="%s" Type="%s" Target="%s"%s/>' % (rid, t, esc(tg), ' TargetMode="External"' if ex else ""))
        out.append("</Relationships>")
        return "".join(out)


# ── 文字工具 ──────────────────────────────────────────────────

_PARA_KEYS = ("align", "lineSpacingMultiple", "lineSpacing", "paraSpaceAfter", "paraSpaceBefore")
_INHERIT_SKIP = {"x", "y", "w", "h", "shape", "fill", "line", "shadow", "rectRadius", "margin", "wrap", "fit", "valign",
                 "placeholder", "name", "rotate", "flipH", "flipV", "adj"}


def _normalize_runs(text, o):
    """→ [{'text', 'options'}...]；字符串里的换行拆成独立段落（同 pptxgenjs）"""
    if text is None:
        text = ""
    if isinstance(text, (str, int, float)):
        items = [{"text": str(text), "options": {}}]
    else:
        items = [r if isinstance(r, dict) else {"text": str(r), "options": {}} for r in text]
    out = []
    for r in items:
        t = "" if r.get("text") is None else str(r.get("text"))
        ro = dict(r.get("options") or {})
        parts = t.replace("\r\n", "\n").split("\n")
        for i, part in enumerate(parts):
            po = dict(ro)
            if i < len(parts) - 1:
                po["breakLine"] = True
            out.append({"text": part, "options": po})
    return out


def _effective(run_opts, o):
    """pptxgenjs 继承规则：run 上「假值」的选项一律继承形状级选项"""
    eff = dict(run_opts)
    for k, v in o.items():
        if k in _INHERIT_SKIP:
            continue
        if not eff.get(k):
            eff[k] = v
    return eff


def _body_pr(o):
    wrap = o.get("wrap", True) is not False
    attrs = ' wrap="%s"' % ("square" if wrap else "none")
    m = o.get("margin")
    if m is not None:
        if isinstance(m, (list, tuple)):
            l, r, b, t = (list(m) + [0, 0, 0, 0])[:4]
        else:
            l = r = b = t = m
        attrs += ' lIns="%d" tIns="%d" rIns="%d" bIns="%d"' % (pts(l), pts(t), pts(r), pts(b))
    attrs += ' rtlCol="0" anchor="%s"' % VALIGN.get(o.get("valign") or "middle", "ctr")
    fit = ""
    if o.get("fit") == "shrink":
        fit = "<a:normAutofit/>"
    elif o.get("fit") == "resize":
        fit = "<a:spAutoFit/>"
    return "<a:bodyPr%s>%s</a:bodyPr>" % (attrs, fit)


def _ppr(eff):
    attrs = ""
    if eff.get("align") in TEXT_ALIGN:
        attrs += ' algn="%s"' % TEXT_ALIGN[eff["align"]]
    inner = ""
    if eff.get("lineSpacing"):
        inner += '<a:lnSpc><a:spcPts val="%d"/></a:lnSpc>' % int(round(eff["lineSpacing"] * 100))
    elif eff.get("lineSpacingMultiple"):
        inner += '<a:lnSpc><a:spcPct val="%d"/></a:lnSpc>' % int(round(eff["lineSpacingMultiple"] * 100000))
    if eff.get("paraSpaceBefore"):
        inner += '<a:spcBef><a:spcPts val="%d"/></a:spcBef>' % int(round(eff["paraSpaceBefore"] * 100))
    if eff.get("paraSpaceAfter"):
        inner += '<a:spcAft><a:spcPts val="%d"/></a:spcAft>' % int(round(eff["paraSpaceAfter"] * 100))
    inner += "<a:buNone/>"
    return '<a:pPr%s indent="0" marL="0">%s</a:pPr>' % (attrs, inner)


def _rpr(eff, tag="a:rPr", fonts=None):
    attrs = ' lang="zh-CN" altLang="en-US"'
    if eff.get("fontSize"):
        attrs += ' sz="%d"' % int(round(float(eff["fontSize"]) * 100))
    if eff.get("bold"):
        attrs += ' b="1"'
    else:
        attrs += ' b="0"'
    if eff.get("italic"):
        attrs += ' i="1"'
    if eff.get("charSpacing"):
        attrs += ' spc="%d" kern="0"' % int(round(float(eff["charSpacing"]) * 100))
    attrs += ' dirty="0"'
    inner = ""
    if eff.get("color"):
        inner += solid_fill(eff["color"], eff.get("transparency", 0))
    face = eff.get("fontFace")
    if face:
        latin = (fonts or {}).get(face, face)
        f = esc(face)
        fl = esc(latin)
        inner += '<a:latin typeface="%s" pitchFamily="34" charset="0"/><a:ea typeface="%s" pitchFamily="34" charset="-122"/><a:cs typeface="%s" pitchFamily="34" charset="-120"/>' % (fl, f, fl)
    return "<%s%s>%s</%s>" % (tag, attrs, inner, tag)


def _paragraphs(runs, o, fonts=None):
    lines = [[]]
    for i, r in enumerate(runs):
        lines[-1].append(r)
        if r["options"].get("breakLine") and i + 1 < len(runs):
            lines.append([])
    out = []
    for line in lines:
        first = _effective(line[0]["options"], o) if line else dict(o)
        p = "<a:p>" + _ppr(first)
        last_sz = None
        for r in line:
            eff = _effective(r["options"], o)
            if eff.get("fontSize"):
                last_sz = eff["fontSize"]
            if r["text"] == "":
                continue
            p += "<a:r>%s<a:t>%s</a:t></a:r>" % (_rpr(eff, fonts=fonts), esc(r["text"]))
        end = {"fontSize": last_sz or o.get("fontSize"), "fontFace": o.get("fontFace")}
        p += _rpr(end, "a:endParaRPr", fonts).replace(' b="0"', "")
        out.append(p + "</a:p>")
    return "".join(out)


def _border_xml(tag, b):
    if b is None or b.get("type") == "none":
        return "<a:%s w=\"0\"><a:noFill/></a:%s>" % (tag, tag)
    w = pts(b.get("pt", 1))
    return ('<a:%s w="%d" cap="flat" cmpd="sng" algn="ctr">%s<a:prstDash val="solid"/><a:round/>'
            '<a:headEnd type="none" w="med" len="med"/><a:tailEnd type="none" w="med" len="med"/></a:%s>') % (
        tag, w, solid_fill(b.get("color", "000000")), tag)


def _table_cell(text, co, table_opts, fonts=None):
    runs = _normalize_runs(text, co)
    body = "<a:bodyPr/><a:lstStyle/>" + _paragraphs(runs, co, fonts)
    margin = co.get("margin")
    if margin is None:
        margin = [0.05, 0.1, 0.05, 0.1]  # pptxgenjs 默认（英寸，上右下左）
    if not isinstance(margin, (list, tuple)):
        margin = [margin] * 4
    if margin[0] >= 1:  # pptxgenjs：≥1 视为磅
        mar = (pts(margin[3]), pts(margin[1]), pts(margin[0]), pts(margin[2]))
    else:
        mar = (emu(margin[3]), emu(margin[1]), emu(margin[0]), emu(margin[2]))
    anchor = VALIGN.get(co.get("valign") or "top", "t")
    border = co.get("border")
    if isinstance(border, (list, tuple)):  # 上右下左
        bt, br, bb, bl = (list(border) + [None] * 4)[:4]
    elif isinstance(border, dict):
        bt = br = bb = bl = border
    else:
        bt = br = bb = bl = None
    if border is None:
        lns = ""
    else:
        lns = _border_xml("lnL", bl) + _border_xml("lnR", br) + _border_xml("lnT", bt) + _border_xml("lnB", bb)
    fx = fill_xml(co.get("fill")) if co.get("fill") else ""
    return ('<a:tc><a:txBody>%s</a:txBody><a:tcPr marL="%d" marR="%d" marT="%d" marB="%d" anchor="%s">%s%s</a:tcPr></a:tc>'
            % (body, mar[0], mar[1], mar[2], mar[3], anchor, lns, fx or ""))
