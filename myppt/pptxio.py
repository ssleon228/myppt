"""读懂、修改用户上传的 PPT（只用标准库）。

pptx 是一个 zip 包，每页是一份 XML。这里做三件事：
1. inventory：列出每页的每个元素（文本框、表格、图片、图形），位置换算成 1920 宽的设计单位，
   并找出「可填的空位」（空文本框、"请输入…"这类提示文字）和「空白区域」。
2. 改文字：只换文字，段落格式、字体、颜色、位置原样保留；改完用真实字宽量，放不下先缩字号，
   缩到下限还放不下就报出来，请用户删减。
3. 补空白：在一块空白区域里用排版引擎排版，画出来的形状直接插进这一页，配色跟随这份 PPT 的主题色。

没提到的页、没提到的元素，XML 一个字节都不动（按原始文本做定点替换，不整体重写）。
"""
import copy
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
A, P_, R = "{%s}" % NS["a"], "{%s}" % NS["p"], "{%s}" % NS["r"]
SHAPE_TAGS = ("p:sp", "p:grpSp", "p:graphicFrame", "p:pic", "p:cxnSp", "mc:AlternateContent", "p:contentPart")
PROMPT_RE = re.compile(r"(请输入|请在此|单击此处|点击此处|点击输入|在此输入|输入文字|添加标题|添加文字|此处添加|标题文字|内容文字|"
                       r"XXX|xxx|×××|\*\*|包含但不限于|待填|待补|Lorem|lorem|Click to|click to|TEXT HERE|Your text|YOUR TEXT)")
EMPTY_MIN_W, EMPTY_MIN_H = 320, 160  # 空白区域至少这么大才报（设计单位）


# ════════════════ 打开文件 ════════════════

class Doc:
    def __init__(self, path_or_bytes):
        data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read()
        z = zipfile.ZipFile(io.BytesIO(data))
        self.order = z.namelist()
        self.files = {n: z.read(n) for n in self.order}
        self.infos = {i.filename: i for i in z.infolist()}
        pres = ET.fromstring(self.files["ppt/presentation.xml"])
        sz = pres.find("p:sldSz", NS)
        self.cx, self.cy = int(sz.get("cx")), int(sz.get("cy"))
        self.k = 1920.0 / self.cx  # EMU → 设计单位
        self.page_h = self.cy * self.k
        rels = self._rels("ppt/presentation.xml")
        self.slides = []
        for sid in pres.find("p:sldIdLst", NS) or []:
            self.slides.append(rels[sid.get(R + "id")])
        self.theme = self._theme()
        self._layout_cache = {}

    # ── 包内路径 ──
    @staticmethod
    def _rels_path(part):
        d, f = part.rsplit("/", 1)
        return "%s/_rels/%s.rels" % (d, f)

    def _rels(self, part):
        """→ {rId: 包内绝对路径}"""
        rp = self._rels_path(part)
        if rp not in self.files:
            return {}
        base = part.rsplit("/", 1)[0]
        out = {}
        for r in ET.fromstring(self.files[rp]):
            t = r.get("Target")
            if r.get("TargetMode") == "External":
                continue
            out[r.get("Id")] = _join(base, t)
        return out

    def rel_of_type(self, part, kind):
        rp = self._rels_path(part)
        if rp not in self.files:
            return None
        base = part.rsplit("/", 1)[0]
        for r in ET.fromstring(self.files[rp]):
            if r.get("Type", "").endswith("/" + kind):
                return _join(base, r.get("Target"))
        return None

    def text(self, part):
        return self.files[part].decode("utf-8")

    def set_text(self, part, s):
        self.files[part] = s.encode("utf-8")

    def save(self, path=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n in self.order:
                z.writestr(self.infos[n] if n in self.infos else n, self.files[n])
        if path:
            with open(path, "wb") as f:
                f.write(buf.getvalue())
        return buf.getvalue()

    # ── 主题：配色和字体 ──
    def _theme(self):
        master = self.rel_of_type(self.slides[0], "slideLayout") if self.slides else None
        master = self.rel_of_type(master, "slideMaster") if master else None
        tp = self.rel_of_type(master, "theme") if master else None
        out = {"colors": {}, "major": {}, "minor": {}}
        if not tp or tp not in self.files:
            return out
        t = ET.fromstring(self.files[tp])
        cs = t.find(".//a:clrScheme", NS)
        if cs is not None:
            for c in cs:
                tag = c.tag.split("}")[1]
                v = c.find("a:srgbClr", NS)
                s = c.find("a:sysClr", NS)
                out["colors"][tag] = (v.get("val") if v is not None else (s.get("lastClr") if s is not None else None))
        for kind in ("major", "minor"):
            f = t.find(".//a:%sFont" % kind, NS)
            if f is not None:
                for k in ("latin", "ea"):
                    e = f.find("a:" + k, NS)
                    if e is not None and e.get("typeface"):
                        out[kind][k] = e.get("typeface")
        return out

    # ── 版式里的占位符位置（页面上的占位符没写位置时继承它）──
    def layout_ph(self, slide_part):
        lp = self.rel_of_type(slide_part, "slideLayout")
        if lp in self._layout_cache:
            return self._layout_cache[lp]
        out = {}
        for part in (self.rel_of_type(lp, "slideMaster") if lp else None, lp):
            if not part or part not in self.files:
                continue
            root = ET.fromstring(self.files[part])
            for sp in root.iter(P_ + "sp"):
                ph = sp.find(".//p:nvPr/p:ph", NS)
                box = _xfrm(sp.find("p:spPr", NS))
                if ph is None or box is None:
                    continue
                out[(ph.get("type") or "body", ph.get("idx") or "")] = box
                out.setdefault((ph.get("type") or "body", None), box)
        self._layout_cache[lp] = out
        return out

    def layout_name(self, slide_part):
        lp = self.rel_of_type(slide_part, "slideLayout")
        if not lp:
            return ""
        c = ET.fromstring(self.files[lp]).find("p:cSld", NS)
        return (c.get("name") if c is not None else "") or ""


def _join(base, target):
    if target.startswith("/"):
        return target.lstrip("/")
    parts = base.split("/")
    for seg in target.split("/"):
        if seg == "..":
            parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    return "/".join(parts)


def _xfrm(sppr):
    if sppr is None:
        return None
    x = sppr.find("a:xfrm", NS)
    if x is None:
        return None
    off, ext = x.find("a:off", NS), x.find("a:ext", NS)
    if off is None or ext is None:
        return None
    return int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))


# ════════════════ 原始 XML 定位（改写时不重排整份文件）════════════════

_TAG = re.compile(r"<(/?)([A-Za-z_][\w.\-]*:?[\w.\-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>")


def tree_children(xml, start_tag="p:spTree"):
    """spTree 的直接子元素在原文里的 (起点, 终点, 标签)"""
    out = []
    depth = 0
    inside = None
    cur = None
    for m in _TAG.finditer(xml):
        close, name, _, selfc = m.group(1), m.group(2), m.group(3), m.group(4)
        if name.startswith("?") or name.startswith("!"):
            continue
        if inside is None:
            if name == start_tag and not close:
                inside = depth
            if not close and not selfc:
                depth += 1
            elif close:
                depth -= 1
            continue
        if close:
            depth -= 1
            if depth == inside:  # spTree 本身结束
                break
            if depth == inside + 1 and cur is not None and name == cur[1]:
                out.append((cur[0], m.end(), name))
                cur = None
        else:
            if depth == inside + 1 and name in SHAPE_TAGS:
                if selfc:
                    out.append((m.start(), m.end(), name))
                else:
                    cur = (m.start(), name)
            if not selfc:
                depth += 1
    return out


def sptree_end(xml):
    i = xml.rfind("</p:spTree>")
    if i < 0:
        raise ValueError("页面里找不到 spTree")
    return i


# ════════════════ 清单 ════════════════

def _shape_text(el):
    paras = []
    for p in el.iter(A + "p"):
        paras.append("".join(t.text or "" for t in p.iter(A + "t")))
    return paras


def _first_sz(el):
    for tag in ("rPr", "endParaRPr", "defRPr"):
        for r in el.iter(A + tag):
            if r.get("sz"):
                return int(r.get("sz")) / 100.0
    return None


def _fill_of(sp):
    sppr = sp.find("p:spPr", NS)
    if sppr is None:
        return None
    f = sppr.find("a:solidFill/a:srgbClr", NS)
    if f is not None:
        return f.get("val")
    g = sppr.find("a:gradFill//a:srgbClr", NS)
    if g is not None:
        return g.get("val")
    sc = sppr.find("a:solidFill/a:schemeClr", NS)
    if sc is None:
        sc = sppr.find("a:gradFill//a:schemeClr", NS)
    if sc is not None:
        return "scheme:" + (sc.get("val") or "")
    # 没写 spPr 填充、靠形状样式（fillRef）给底色的普通图形
    ref = sp.find("p:style/a:fillRef", NS)
    if ref is not None and ref.get("idx") not in (None, "0") and sppr.find("a:noFill", NS) is None:
        return "style"
    return None


def _has_line(sp):
    sppr = sp.find("p:spPr", NS)
    ln = sppr.find("a:ln", NS) if sppr is not None else None
    if ln is not None:
        if ln.find("a:noFill", NS) is not None:
            return False
        if ln.find("a:solidFill", NS) is not None or ln.find("a:gradFill", NS) is not None:
            return True
    ref = sp.find("p:style/a:lnRef", NS)
    return ref is not None and ref.get("idx") not in (None, "0")


def inventory(doc):
    """→ [{slide, layout, shapes:[...], slots:[...], blanks:[...]}]"""
    out = []
    for si, part in enumerate(doc.slides):
        xml = doc.text(part)
        root = ET.fromstring(xml)
        tree = root.find("p:cSld/p:spTree", NS)
        kids = [c for c in tree if c.tag.split("}")[1] in ("sp", "grpSp", "graphicFrame", "pic", "cxnSp", "AlternateContent",
                                                           "contentPart")]
        lph = doc.layout_ph(part)
        shapes = []
        for i, el in enumerate(kids):
            tag = el.tag.split("}")[1]
            nv = el.find(".//p:cNvPr", NS)
            ph = el.find(".//p:nvPr/p:ph", NS)
            box = None
            if tag == "sp" or tag == "pic" or tag == "cxnSp":
                box = _xfrm(el.find("p:spPr", NS))
            elif tag == "grpSp":
                box = _xfrm(el.find("p:grpSpPr", NS))
            elif tag == "graphicFrame":
                x = el.find("p:xfrm", NS)
                if x is not None:
                    off, ext = x.find("a:off", NS), x.find("a:ext", NS)
                    box = int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))
            if box is None and ph is not None:
                box = lph.get((ph.get("type") or "body", ph.get("idx") or "")) or lph.get((ph.get("type") or "body", None))
            kind = {"sp": "shape", "grpSp": "group", "graphicFrame": "frame", "pic": "picture", "cxnSp": "line"}.get(tag, tag)
            item = {"i": i, "id": nv.get("id") if nv is not None else "", "name": nv.get("name") if nv is not None else "",
                    "kind": kind}
            if ph is not None:
                item["placeholder"] = ph.get("type") or "body"
            if box:
                item["box"] = [round(v * doc.k) for v in box]
            if tag == "sp" and el.find("p:txBody", NS) is not None:
                item["kind"] = "text"
                paras = _shape_text(el.find("p:txBody", NS))
                item["text"] = "\n".join(paras).strip()
                item["size"] = _first_sz(el)
                f = _fill_of(el)
                if f:
                    item["fill"] = f
                if _has_line(el):
                    item["outline"] = True
            elif tag == "sp":
                f = _fill_of(el)
                if f:
                    item["fill"] = f
            elif tag == "graphicFrame":
                tbl = el.find(".//a:tbl", NS)
                if tbl is not None:
                    item["kind"] = "table"
                    item["cells"] = [["\n".join(_shape_text(tc)).strip() for tc in tr.findall("a:tc", NS)]
                                     for tr in tbl.findall("a:tr", NS)]
                elif el.find(".//{http://schemas.openxmlformats.org/drawingml/2006/chart}chart", NS) is not None:
                    item["kind"] = "chart"
            elif tag == "grpSp":
                item["text"] = "\n".join(t.text or "" for t in el.iter(A + "t")).strip()
            shapes.append(item)
        rec = {"slide": si + 1, "part": part, "layout": doc.layout_name(part), "shapes": shapes}
        rec["slots"] = _slots(shapes, doc)
        rec["blanks"] = blanks(shapes, doc)
        out.append(rec)
    return out


def _slots(shapes, doc):
    """可填的空位：空文本框 / 只有提示文字的文本框（太小的装饰小框不算）"""
    out = []
    for s in shapes:
        if s["kind"] != "text" or "box" not in s:
            continue
        x, y, w, h = s["box"]
        if w < 120 or h < 40:
            continue
        t = s.get("text") or ""
        if not t and s.get("fill"):
            continue  # 有底色的空框是装饰色块（比如 Banner 底条），不是空位
        if not t and any(o is not s and o.get("box") and o.get("kind") == "text" and (o.get("text") or "").strip()
                         and _inside(o["box"], s["box"]) for o in shapes):
            continue  # 里面已经放了别的文字的边框，填它会盖住里面的字；按空白区域处理
        if not t or PROMPT_RE.search(t):
            out.append({"i": s["i"], "id": s["id"], "box": s["box"], "now": t,
                        "why": "空文本框" if not t else "提示文字"})
    return out


def _inside(b, c):
    return b[0] >= c[0] - 2 and b[1] >= c[1] - 2 and b[0] + b[2] <= c[0] + c[2] + 2 and b[1] + b[3] <= c[1] + c[3] + 2


def blanks(shapes, doc, cell=24):
    """空白区域：把内容元素铺到网格上，找最大的空矩形（整页背景、页外元素不算内容）"""
    W, H = 1920, int(doc.page_h)
    cols, rows = W // cell, H // cell
    occ = [[False] * cols for _ in range(rows)]
    for s in shapes:
        if "box" not in s:
            continue
        x, y, w, h = s["box"]
        if w * h > W * H * 0.85:  # 背景
            continue
        if s["kind"] == "text" and not (s.get("text") or "").strip() and not s.get("fill"):
            if s.get("outline"):  # 空边框：只占边线一圈，空白区域要么在框里、要么在框外，不会骑在边上
                c0, c1 = max(0, int(x // cell)), min(cols, int((x + w) // cell) + 1)
                r0, r1 = max(0, int(y // cell)), min(rows, int((y + h) // cell) + 1)
                for r in range(r0, r1):
                    for c in range(c0, c1):
                        if r in (r0, r0 + 1, r1 - 2, r1 - 1) or c in (c0, c0 + 1, c1 - 2, c1 - 1):  # 两格宽，避开圆角
                            occ[r][c] = True
            continue  # 空文本框本身就是可填的地方
        c0, c1 = max(0, int(x // cell)), min(cols, int((x + w) // cell) + 1)
        r0, r1 = max(0, int(y // cell)), min(rows, int((y + h) // cell) + 1)
        for r in range(r0, r1):
            for c in range(c0, c1):
                occ[r][c] = True
    # 页边距：左右 48、上下 36 不算空白
    mx, my = 2, 2
    found = []
    taken = [[False] * cols for _ in range(rows)]
    for _ in range(3):
        best = _max_rect(occ, taken, mx, my, cols - mx, rows - my)
        if not best:
            break
        r0, c0, r1, c1 = best
        w, h = (c1 - c0) * cell, (r1 - r0) * cell
        if w < EMPTY_MIN_W or h < EMPTY_MIN_H:
            break
        m = cell // 2  # 离周围元素留一点距离
        found.append({"box": [c0 * cell + m, r0 * cell + m, w - 2 * m, h - 2 * m], "area": round(w * h / float(W * H), 3)})
        for r in range(r0, r1):
            for c in range(c0, c1):
                taken[r][c] = True
    return found


def _max_rect(occ, taken, c_lo, r_lo, c_hi, r_hi):
    """直方图法求最大全空矩形 → (r0, c0, r1, c1)"""
    width = c_hi - c_lo
    hts = [0] * width
    best, best_a = None, 0
    for r in range(r_lo, r_hi):
        for j in range(width):
            c = c_lo + j
            hts[j] = hts[j] + 1 if not (occ[r][c] or taken[r][c]) else 0
        stack = []
        for j in range(width + 1):
            hcur = hts[j] if j < width else 0
            start = j
            while stack and stack[-1][1] >= hcur:
                s, hh = stack.pop()
                a = hh * (j - s)
                if a > best_a:
                    best_a, best = a, (r - hh + 1, c_lo + s, r + 1, c_lo + j)
                start = s
            stack.append((start, hcur))
    return best


def describe(inv):
    """清单 → 给模型/用户看的简明文字"""
    lines = []
    for rec in inv:
        lines.append("第 %d 页（版式：%s）" % (rec["slide"], rec["layout"] or "—"))
        for s in rec["shapes"]:
            b = s.get("box")
            pos = "@%d,%d %dx%d" % tuple(b) if b else ""
            if s["kind"] == "text":
                t = (s.get("text") or "").replace("\n", " / ")
                lines.append("  [%d] 文本 %s %s：%s" % (s["i"], pos, ("%gpt" % s["size"]) if s.get("size") else "",
                                                     (t[:60] + "…") if len(t) > 60 else (t or "（空）")))
            elif s["kind"] == "table":
                lines.append("  [%d] 表格 %s：%d 行 × %d 列，首行 %s" % (s["i"], pos, len(s["cells"]),
                                                                max((len(r) for r in s["cells"]), default=0),
                                                                " | ".join(s["cells"][0]) if s["cells"] else ""))
            else:
                lines.append("  [%d] %s %s %s" % (s["i"], {"picture": "图片", "group": "组合", "chart": "图表", "line": "线条",
                                                         "shape": "图形", "frame": "对象"}.get(s["kind"], s["kind"]), pos,
                                                (s.get("text") or "")[:40]))
        for sl in rec["slots"]:
            lines.append("  ★ 可填空位 [%d]（%s）" % (sl["i"], sl["why"]))
        for k, bl in enumerate(rec["blanks"]):
            lines.append("  ☐ 空白区域 %d：@%d,%d %dx%d（占页面 %d%%）" % ((k + 1,) + tuple(bl["box"]) + (round(bl["area"] * 100),)))
    return "\n".join(lines)


# ════════════════ 改文字 ════════════════

_P_RE = re.compile(r"<a:p>.*?</a:p>|<a:p\s[^>]*?/>|<a:p/>|<a:p\s[^>]*>.*?</a:p>", re.S)


def _para_parts(pxml):
    ppr = re.search(r"<a:pPr\b[^>]*/>|<a:pPr\b[^>]*[^/]>.*?</a:pPr>", pxml, re.S)
    rpr = re.search(r"<a:rPr\b[^>]*/>|<a:rPr\b[^>]*[^/]>.*?</a:rPr>", pxml, re.S)
    end = re.search(r"<a:endParaRPr\b[^>]*/>|<a:endParaRPr\b[^>]*[^/]>.*?</a:endParaRPr>", pxml, re.S)
    rp = rpr.group(0) if rpr else None
    if rp is None and end is not None:
        rp = end.group(0).replace("<a:endParaRPr", "<a:rPr", 1).replace("</a:endParaRPr>", "</a:rPr>")
    return (ppr.group(0) if ppr else ""), rp


def _with_sz(rpr, sz):
    if rpr is None:
        return '<a:rPr lang="zh-CN" sz="%d"/>' % sz if sz else '<a:rPr lang="zh-CN"/>'
    if sz is None:
        return rpr
    if re.search(r'\ssz="\d+"', rpr.split(">")[0]):
        return re.sub(r'(<a:rPr\b[^>]*?)\ssz="\d+"', r'\1 sz="%d"' % sz, rpr, count=1)
    return rpr.replace("<a:rPr", '<a:rPr sz="%d"' % sz, 1)


def build_paras(old_body, text, sz=None):
    """按旧段落的格式写新文字：第 i 行用第 i 段的格式（超出的沿用最后一段）"""
    olds = _P_RE.findall(old_body) or ["<a:p/>"]
    parts = [_para_parts(p) for p in olds]
    out = []
    for i, line in enumerate(str(text).split("\n")):
        ppr, rpr = parts[min(i, len(parts) - 1)]
        rpr2 = _with_sz(rpr, sz)
        end = rpr2.replace("<a:rPr", "<a:endParaRPr", 1).replace("</a:rPr>", "</a:endParaRPr>")
        if line:
            out.append("<a:p>%s<a:r>%s<a:t>%s</a:t></a:r></a:p>" % (ppr, rpr2, escape(line)))
        else:
            out.append("<a:p>%s%s</a:p>" % (ppr, end))
    return "".join(out)


def _replace_body(shape_xml, text, sz=None, body_tag="p:txBody"):
    m = re.search(r"<%s>(.*?)</%s>" % (body_tag, body_tag), shape_xml, re.S)
    if not m:
        return None
    inner = m.group(1)
    head = re.match(r"\s*(<a:bodyPr\b[^>]*/>|<a:bodyPr\b.*?</a:bodyPr>)?\s*(<a:lstStyle\s*/>|<a:lstStyle>.*?</a:lstStyle>)?",
                    inner, re.S)
    keep = (head.group(1) or "<a:bodyPr/>") + (head.group(2) or "<a:lstStyle/>")
    body = inner[head.end():]
    new = keep + build_paras(body, text, sz)
    return shape_xml[:m.start(1)] + new + shape_xml[m.end(1):]


def _fit(doc, shape, text):
    """→ (新字号 百分之一磅或 None, 警告或 None)。按真实字宽量一下放不放得下"""
    from . import measure as M
    if "box" not in shape:
        return None, None
    x, y, w, h = shape["box"]
    pt = shape.get("size") or 18.0
    pxpt = 1920.0 / (doc.cx / 914400.0 * 72)  # 1 磅 = 多少设计单位
    iw, ih = max(20, w - 2 * 10 * pxpt / 1.0), max(10, h - 2 * 5 * pxpt / 1.0)
    iw = max(20, w - 0.2 * 72 * pxpt)  # 默认左右内边距 0.1 英寸
    ih = max(10, h - 0.1 * 72 * pxpt)

    def need(p, t=text):
        return sum(M.text_h(line or " ", iw, p * pxpt, 1.2) for line in str(t).split("\n"))
    # 模板原来的字在原字号下就比框高（设计者有意让字溢出框外一点）：以原来的高度为准，别白白缩字
    old = shape.get("text")
    if old:
        ih = max(ih, need(pt, old))
    if need(pt) <= ih * 1.02 or shape.get("autogrow"):
        return None, None
    lo = max(10.0, pt * 0.6)
    p = pt
    while p > lo:
        p = max(lo, p - 0.5)
        if need(p) <= ih * 1.02:
            return int(p * 100), "字号从 %g 磅缩到 %g 磅才放得下" % (pt, p)
    over = need(lo) / ih
    return int(lo * 100), "缩到 %g 磅仍放不下（超出约 %d%%），建议删减文字" % (lo, round((over - 1) * 100))


def _insets(sx, pxpt):
    """文本框左右内边距（设计单位），没写就是默认 0.1 英寸"""
    m = re.search(r"<a:bodyPr\b[^>]*>", sx or "")
    tag = m.group(0) if m else ""
    l = re.search(r'lIns="(\d+)"', tag)
    r = re.search(r'rIns="(\d+)"', tag)
    emu = (int(l.group(1)) if l else 91440) + (int(r.group(1)) if r else 91440)
    return emu / 914400.0 * 72 * pxpt


def fit_line(doc, shape, text, sx=None, min_pt=14.0):
    """标题类：必须一行放下 → (字号 百分之一磅或 None, 警告或 None)。算上字间距和内边距，再留 4% 余量"""
    from . import measure as M
    if "box" not in shape:
        return None, None
    w = shape["box"][2]
    pt = shape.get("size") or 24.0
    pxpt = 1920.0 / (doc.cx / 914400.0 * 72)
    iw = max(20, (w - _insets(sx, pxpt)) * 0.96)
    spc = re.search(r'<a:rPr\b[^>]*\sspc="(-?\d+)"', sx or "")
    spc_pt = int(spc.group(1)) / 100.0 if spc else 0.0
    t = str(text)

    def width(p):
        return M.text_w(t, p * pxpt, True) + len(t) * spc_pt * pxpt
    if width(pt) <= iw:
        return None, None
    p = pt
    while p > min_pt:
        p -= 0.5
        if width(p) <= iw:
            return int(p * 100), "标题字号从 %g 磅缩到 %g 磅才能一行放下" % (pt, p)
    return int(min_pt * 100), "标题太长，缩到 %g 磅仍放不下一行，建议缩短" % min_pt


def apply_ops(doc, ops, inv=None):
    """ops: [{slide, shape(序号 i 或 id), text} | {slide, shape, cell:[行,列], text} | {slide, region|blank, layout|page}]
    → 报告 [(slide, 说明)]"""
    inv = inv or inventory(doc)
    report = []
    by_slide = {}
    for op in ops:
        by_slide.setdefault(int(op.get("slide", 0)), []).append(op)
    for sn, sops in sorted(by_slide.items()):
        if not 1 <= sn <= len(doc.slides):
            report.append((sn, "没有第 %d 页，跳过" % sn))
            continue
        part = doc.slides[sn - 1]
        rec = inv[sn - 1]
        xml = doc.text(part)
        spans = tree_children(xml)
        edits = []  # (start, end, new)
        inserts = []
        for op in sops:
            if "text" in op and ("shape" in op):
                s = _find_shape(rec, op["shape"])
                if s is None or s["i"] >= len(spans):
                    report.append((sn, "找不到元素 %r" % op["shape"]))
                    continue
                st, en, _ = spans[s["i"]]
                sx = xml[st:en]
                if "cell" in op:
                    new = _replace_cell(sx, op["cell"], op["text"])
                    if new is None:
                        report.append((sn, "表格 [%d] 没有第 %s 格" % (s["i"], op["cell"])))
                        continue
                    edits.append((st, en, new))
                    report.append((sn, "表格 [%d] 第 %d 行第 %d 列 → %s" % (s["i"], op["cell"][0], op["cell"][1], op["text"])))
                    continue
                sz, warn = _fit(doc, dict(s, autogrow="<a:spAutoFit" in sx), op["text"])
                new = _replace_body(sx, op["text"], sz)
                if new is not None and not s.get("fill") and not _has_backdrop(rec, s) and _white_text(new):
                    new = _darken_text(new, theme_palette(doc, xml)["ink"])
                    warn = ((warn + "；") if warn else "") + "原来的字是白色，框里没有底色会看不见，已改成深色"
                if new is None:
                    report.append((sn, "元素 [%d] 不是文本框，不能改文字" % s["i"]))
                    continue
                edits.append((st, en, new))
                report.append((sn, "文本 [%d] 改为：%s%s" % (s["i"], op["text"].replace("\n", " / ")[:50],
                                                       ("（%s）" % warn) if warn else "")))
            elif "layout" in op or "page" in op:
                box = op.get("region")
                if box is None:
                    bi = int(op.get("blank", 1)) - 1
                    if not 0 <= bi < len(rec["blanks"]):
                        report.append((sn, "这页没有第 %d 块空白区域" % (bi + 1)))
                        continue
                    box = rec["blanks"][bi]["box"]
                frag, note = render_region(doc, part, xml, box, op)
                if frag is None:
                    report.append((sn, note))
                    continue
                inserts.append(frag)
                report.append((sn, "空白区域 @%d,%d %dx%d 补上内容（%s）" % (tuple(box) + (note,))))
        for st, en, new in sorted(edits, reverse=True):
            xml = xml[:st] + new + xml[en:]
        if inserts:
            i = sptree_end(xml)
            xml = xml[:i] + "".join(inserts) + xml[i:]
        doc.set_text(part, xml)
    return report


_WHITE = re.compile(r'<a:solidFill>\s*(?:<a:srgbClr val="(?:FFFFFF|ffffff|FEFEFE|FAFAFA)"\s*/?>(?:</a:srgbClr>)?|'
                    r'<a:prstClr val="white"\s*/?>(?:</a:prstClr>)?|<a:schemeClr val="(?:lt1|bg1)"\s*/?>(?:</a:schemeClr>)?)\s*</a:solidFill>')


def _has_backdrop(rec, s):
    """文字框下面（更早画的）有没有带底色的图形或图片垫着"""
    if "box" not in s:
        return True
    x, y, w, h = s["box"]
    cx, cy = x + w / 2.0, y + h / 2.0
    for o in rec["shapes"]:
        if o["i"] >= s["i"] or "box" not in o:
            continue
        if o.get("fill") or o["kind"] in ("picture", "group"):
            ox, oy, ow, oh = o["box"]
            if ox <= cx <= ox + ow and oy <= cy <= oy + oh:
                return True
    return False


def _white_text(shape_xml):
    body = re.search(r"<p:txBody>.*?</p:txBody>", shape_xml, re.S)
    if not body:
        return False
    rprs = re.findall(r"<a:rPr\b[^>]*/>|<a:rPr\b[^>]*[^/]>.*?</a:rPr>", body.group(0), re.S)
    if rprs:
        return all(_WHITE.search(r) for r in rprs)
    # 文字颜色来自形状样式（fontRef 里的 lt1）
    return bool(re.search(r'<a:fontRef[^>]*>\s*<a:schemeClr val="(?:lt1|bg1)"', shape_xml))


def _darken_text(shape_xml, ink):
    m = re.search(r"<p:txBody>.*?</p:txBody>", shape_xml, re.S)
    body = m.group(0)
    fill = '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % ink
    body2 = _WHITE.sub(fill, body)

    def add(rm):
        r = rm.group(0)
        if "<a:solidFill>" in r:
            return r
        if r.endswith("/>"):
            return r[:-2] + ">" + fill + "</a:rPr>"
        i = r.find(">") + 1
        return r[:i] + fill + r[i:]
    body2 = re.sub(r"<a:rPr\b[^>]*/>|<a:rPr\b[^>]*[^/]>.*?</a:rPr>", add, body2, flags=re.S)
    return shape_xml[:m.start()] + body2 + shape_xml[m.end():]


def _find_shape(rec, key):
    """整数 = 清单里的 [序号]；字符串 = 元素 id 或名字"""
    if isinstance(key, int):
        return next((s for s in rec["shapes"] if s["i"] == key), None)
    for s in rec["shapes"]:
        if str(s["id"]) == str(key) or s["name"] == key:
            return s
    try:
        k = int(key)
        return next((s for s in rec["shapes"] if s["i"] == k), None)
    except (TypeError, ValueError):
        return None


def _replace_cell(frame_xml, cell, text):
    r, c = int(cell[0]), int(cell[1])
    trs = list(re.finditer(r"<a:tr\b.*?</a:tr>", frame_xml, re.S))
    if not 1 <= r <= len(trs):
        return None
    tr = trs[r - 1]
    tcs = list(re.finditer(r"<a:tc\b.*?</a:tc>", tr.group(0), re.S))
    if not 1 <= c <= len(tcs):
        return None
    tc = tcs[c - 1]
    new_tc = _replace_body(tc.group(0), text, None, "a:txBody")
    if new_tc is None:
        return None
    new_tr = tr.group(0)[:tc.start()] + new_tc + tr.group(0)[tc.end():]
    return frame_xml[:tr.start()] + new_tr + frame_xml[tr.end():]


# ════════════════ 补空白：用排版引擎排，再把形状插进这一页 ════════════════

def page_colors(xml):
    """页面上图形实际用的颜色（很多模板主题色是默认的，真正的品牌色直接画在页面上）→ 按出现次数排的鲜明色"""
    from . import palette as PL
    cnt = {}
    for sp in re.findall(r"<p:spPr\b.*?</p:spPr>", xml, re.S):
        sp = re.sub(r"<a:ln\b.*?</a:ln>", "", sp, flags=re.S)
        for v in re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', sp):
            hh, sat, l = PL.hsl(v.upper())
            if sat > 0.3 and 0.2 < l < 0.65:
                cnt[v.upper()] = cnt.get(v.upper(), 0) + 1
    return [k for k, _ in sorted(cnt.items(), key=lambda kv: -kv[1])]


def theme_palette(doc, xml=None):
    from . import palette as PL
    c = doc.theme.get("colors") or {}
    office = c.get("accent1", "").upper() in ("4F81BD", "4472C4", "156082", "")  # Office 默认主题色
    seen = page_colors(xml) if xml else []
    seed = (seen[0] if seen and (office or not c.get("accent1")) else None) or c.get("accent1") or "1F5FAD"
    pal, _ = PL.build({"primary": seed})
    if len(seen) > 1 and seed == seen[0]:
        pal["secondary"] = seen[1]
        pal["secondary_text"] = PL.darken_until(seen[1], "FFFFFF", 3.2)
    elif c.get("accent2") and not office:
        pal["secondary"] = c["accent2"]
        pal["secondary_text"] = PL.darken_until(c["accent2"], "FFFFFF", 3.2)
    return pal


def render_region(doc, slide_part, slide_xml, box, op):
    """在 box（设计单位）里排版 → (要插进 spTree 的 XML, 说明)"""
    from .engine import render as PR
    from .engine.ooxml.package import Presentation
    from . import tokens, measure, styles as STY
    from .render import draw_tree, try_tree
    from .spec import normalize
    from .autodesign import candidates
    lay = op.get("layout")
    trees = []
    if lay:
        t, fixes, errs = normalize(lay)
        if t is None or errs:
            return None, "版面结构有误：%s" % "；".join(errs)
        trees.append(("AI版面", t))
    if op.get("page"):
        for name, t in candidates(op["page"]):
            t2, _, er = normalize(t)
            if t2 is not None and not er:
                trees.append((name, t2))
    if not trees:
        return None, "没有可排的内容"
    # 只允许不需要额外部件的元素（图表、图片要另建关联文件，补空白时不支持）
    bad = {"chart", "image", "hub"}  # 中心辐射图的文字会伸出区域，补空白时不用
    trees = [(n, t) for n, t in trees if not _uses(t, bad)]
    if not trees:
        return None, "补空白暂不支持图表和图片"
    th = doc.theme
    cn = (th.get("minor") or {}).get("ea") or (th.get("major") or {}).get("ea") or "微软雅黑"
    latin = (th.get("minor") or {}).get("latin") or None
    if cn.startswith("+"):
        cn = "微软雅黑"
    if latin and latin.startswith("+"):
        latin = None
    PR.K.FONT, PR.K.LATIN, PR.K.FONT_HEI = cn, latin, cn
    PR.K.page_icons = set()
    PR.K.icons_on = True
    measure.set_fonts(cn, latin)
    STY.use(op.get("style") or "corporate")
    saved = dict(tokens.AREA)
    x, y, w, h = [float(v) for v in box]
    pad = 16
    tokens.AREA.update(dict(x=x + pad, y=y + pad, w=w - 2 * pad, h=h - 2 * pad))
    best = None
    try:
        for name, t in trees:
            STY.remap(t)
            res = try_tree(t)
            if not res["ok"]:
                continue
            from .render import score, _holes
            from .spec import signature, family
            sc = score(res, None, signature(t), (), family(t), _holes(t)) + STY.bonus(name)
            if best is None or sc > best[0]:
                best = (sc, name, res)
        if best is None:
            return None, "这块空白太小，内容放不下"
        pal = theme_palette(doc, slide_xml)
        pres = Presentation(13.333, 13.333 * doc.cy / doc.cx, title="")
        pres.add_layout("blank", "blank")
        slide = pres.add_slide()
        draw_tree(slide, best[2], pal, [])
        data = pres.to_bytes()
    finally:
        tokens.AREA.clear()
        tokens.AREA.update(saved)
    tmp = zipfile.ZipFile(io.BytesIO(data))
    sx = tmp.read("ppt/slides/slide1.xml").decode("utf-8")
    spans = tree_children(sx)
    frag = "".join(sx[a:b] for a, b, _ in spans)
    # 尺寸换算（临时页按 13.333 英寸宽画）+ 元素编号接着这一页往后排
    scale = doc.cx / 12192000.0
    if abs(scale - 1) > 1e-6:
        frag = re.sub(r'(<a:(?:off|ext|chOff|chExt)\s+)([^/]*)/>',
                      lambda m: m.group(1) + re.sub(r'(\w+)="(-?\d+)"', lambda q: '%s="%d"' % (q.group(1), int(int(q.group(2)) * scale)),
                                                     m.group(2)) + "/>", frag)
        frag = re.sub(r'\bsz="(\d+)"', lambda q: 'sz="%d"' % max(100, int(int(q.group(1)) * scale)), frag)
    used = [int(v) for v in re.findall(r'<p:cNvPr\s+id="(\d+)"', slide_xml)] or [1]
    nxt = [max(used) + 1]

    def renum(m):
        v = nxt[0]
        nxt[0] += 1
        return '<p:cNvPr id="%d"' % v
    frag = re.sub(r'<p:cNvPr\s+id="\d+"', renum, frag)
    if "r:embed" in frag or "r:id=" in frag:
        return None, "排出来的内容带图片，补空白暂不支持"
    return frag, "版式 %s，字号档 %d" % (best[1], best[2]["level"])


def _uses(n, els):
    if "el" in n:
        return n["el"] in els
    return any(_uses(c, els) for c in n.get("children") or [])
