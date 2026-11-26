"""方式 A：用用户上传的 PPT 当模板，重新生成一份。

规则：封面、目录、章节页、封底照模板原样，只换文字；内容页保留模板的 Banner（标题条、Logo 等），
Banner 以下交给排版引擎自由设计。母版直接用上传文件自带的。

模板的 Banner 可能画在母版里，也可能直接画在每一页上（很多模板母版是空的）：
  · 母版里有图形：直接继承，内容页只需换标题
  · 母版是空的：比较各内容页，同一位置反复出现的元素就是模板元素；只有一页内容页时，按「页面顶部一条」来认
认出来的结果先给用户确认（analyze → describe_analysis），认不准的列在 unsure 里。
"""
import copy
import io
import re
import zipfile
import xml.etree.ElementTree as ET

from . import pptxio as X

END_RE = re.compile(r"谢谢|感谢|THANK|Thank|thank|END|敬请|欢迎.*指导|再见|Q\s*&\s*A")
TOC_RE = re.compile(r"目\s*录|CONTENTS|Contents|AGENDA|Agenda|议\s*题|大\s*纲|OUTLINE|Outline")
DIGIT_RE = re.compile(r"^\s*(PART\s*)?0?\d{1,2}\s*$|^\s*[一二三四五六七八九十]\s*$|^\s*第[一二三四五六七八九十\d]+[章部分篇]\s*$")


def _sig(s, tol=12):
    b = s.get("box") or [0, 0, 0, 0]
    return (s["kind"], round(b[0] / tol), round(b[1] / tol), round(b[2] / tol), round(b[3] / tol))


def _texts(rec):
    return [s for s in rec["shapes"] if s["kind"] == "text" and (s.get("text") or "").strip()]


def _biggest_text(shapes):
    ts = [s for s in shapes if s["kind"] == "text" and (s.get("text") or "").strip() and "box" in s]
    if not ts:
        return None
    return max(ts, key=lambda s: ((s.get("size") or 18), s["box"][2] * s["box"][3]))


def _master_top_band(doc, part):
    """母版 / 版式里画在顶部的非占位图形 → 最下沿（设计单位），没有返回 0"""
    lp = doc.rel_of_type(part, "slideLayout")
    bottom = 0
    for p in (doc.rel_of_type(lp, "slideMaster") if lp else None, lp):
        if not p or p not in doc.files:
            continue
        root = ET.fromstring(doc.files[p])
        tree = root.find("p:cSld/p:spTree", X.NS)
        if tree is None:
            continue
        for el in tree:
            if el.find(".//p:nvPr/p:ph", X.NS) is not None:
                continue
            box = X._xfrm(el.find("p:spPr", X.NS)) or X._xfrm(el.find("p:grpSpPr", X.NS))
            if not box:
                continue
            y, h = box[1] * doc.k, box[3] * doc.k
            if y < doc.page_h * 0.22 and h < doc.page_h * 0.3:
                bottom = max(bottom, y + h)
    return bottom


def analyze(doc, inv=None):
    """→ dict：各类页用模板里的哪一页、内容页保留哪些元素、标题框、内容区域、需要用户确认的地方"""
    inv = inv or X.inventory(doc)
    n = len(inv)
    res = {"cover": 0 if n else None, "toc": None, "chapter": None, "end": None, "content": None,
           "keep": [], "title": None, "area": None, "notes": [], "unsure": []}
    if n == 0:
        res["unsure"].append("文件里没有页面")
        return res
    # 封底：最后一页，有「谢谢」类文字，或者元素很少
    last = inv[-1]
    lt = " ".join(s.get("text") or "" for s in last["shapes"])
    if n > 1 and (END_RE.search(lt) or len(_texts(last)) <= 2):
        res["end"] = n - 1
    elif n > 1:
        res["unsure"].append("最后一页不像封底（没有“谢谢”类文字），暂不当封底用")
    # 目录
    for i in range(1, min(n, 4)):
        if TOC_RE.search(" ".join(s.get("text") or "" for s in inv[i]["shapes"])):
            res["toc"] = i
            break
    # 章节页：版式名带“节/章/section”，或者一个大号序号 + 很少的文字
    for i in range(1, n - (1 if res["end"] is not None else 0)):
        if i == res["toc"]:
            continue
        rec = inv[i]
        ln = (rec["layout"] or "").lower()
        ts = _texts(rec)
        big_digit = any(DIGIT_RE.match(s["text"]) and (s.get("size") or 0) >= 36 for s in ts)
        if ("节" in ln or "章" in ln or "section" in ln) or (big_digit and len(ts) <= 5):
            res["chapter"] = i
            break
    # 内容页：剩下的页
    special = {res["cover"], res["toc"], res["chapter"], res["end"]}
    cands = [i for i in range(n) if i not in special]
    if not cands:
        res["unsure"].append("没有找到内容页：模板里只有封面/目录/封底，内容页的 Banner 无从参考")
        return res
    # 反复出现的元素（同类型、同位置、同大小）
    counts = {}
    for i in cands:
        for sg in set(_sig(s) for s in inv[i]["shapes"] if "box" in s):
            counts[sg] = counts.get(sg, 0) + 1
    H = doc.page_h
    if len(cands) >= 2:
        need = max(2, int(len(cands) * 0.5 + 0.5))
        rep = {sg for sg, c in counts.items() if c >= need}
        how = "比较了 %d 页内容页，同一位置反复出现的元素当作模板元素" % len(cands)
    else:
        rep = None
        how = "只有 1 页内容页，按页面顶部那一条认 Banner"
    # 选最干净的一页当内容页模板：模板元素多、其他元素少
    best = None
    for i in cands:
        rec = inv[i]
        if rep is not None:
            keep = [s for s in rec["shapes"] if "box" in s and _sig(s) in rep]
        else:
            keep = [s for s in rec["shapes"] if "box" in s and s["box"][1] + s["box"][3] <= H * 0.2]
        # 只保留顶部 / 底部的模板元素（内容区里反复出现的框是旧内容的格式，不是模板）
        keep = [s for s in keep if s["box"][1] + s["box"][3] <= H * 0.22 or s["box"][1] >= H * 0.9]
        other = len(rec["shapes"]) - len(keep)
        sc = (len(keep), -other)
        if best is None or sc > best[0]:
            best = (sc, i, keep)
    _, ci, keep = best
    res["content"] = ci
    rec = inv[ci]
    top_keep = [s for s in keep if s["box"][1] < H * 0.22]
    # 标题框：顶部带里字最大的文本框（母版里的标题占位符也算）
    title = _biggest_text(top_keep) or next((s for s in rec["shapes"] if s.get("placeholder") in ("title", "ctrTitle")), None)
    if title is None:
        title = _biggest_text([s for s in rec["shapes"] if "box" in s and s["box"][1] < H * 0.22])
        if title is not None:
            keep.append(title)
    if title is None:
        res["unsure"].append("内容页没认出标题框，会在 Banner 下方另起标题")
    res["title"] = title["i"] if title else None
    res["keep"] = sorted(set(s["i"] for s in keep) | ({title["i"]} if title else set()))
    # 内容区：模板顶部元素（含母版）最下沿以下，底部元素以上
    top = max([s["box"][1] + s["box"][3] for s in top_keep if s["box"][2] > 1920 * 0.25] or [0])
    top = max(top, _master_top_band(doc, rec["part"]))
    if title and title["box"][1] + title["box"][3] > top:
        top = title["box"][1] + title["box"][3]
    bottom_els = [s["box"][1] for s in keep if s["box"][1] >= H * 0.9]
    bottom = min(bottom_els) if bottom_els else H
    y0 = top + 40 if top else 150
    y1 = bottom - 36
    res["area"] = dict(x=96, y=round(y0), w=1728, h=round(y1 - y0))
    res["notes"].append(how)
    if top == 0:
        res["unsure"].append("没认出 Banner（内容页顶部没有反复出现的元素），内容区从页面上方 150 处开始")
    return res


def describe_analysis(doc, res, inv=None):
    inv = inv or X.inventory(doc)
    name = {"cover": "封面", "toc": "目录页", "chapter": "章节页", "end": "封底", "content": "内容页"}
    out = []
    for k in ("cover", "toc", "chapter", "content", "end"):
        v = res.get(k)
        out.append("%s：%s" % (name[k], ("模板第 %d 页" % (v + 1)) if v is not None else "模板里没有（%s）" % (
            "这类页不生成" if k in ("toc", "chapter") else "用默认画法")))
    if res.get("content") is not None:
        rec = inv[res["content"]]
        keep = [s for s in rec["shapes"] if s["i"] in res["keep"]]
        out.append("内容页保留的模板元素：%s" % "、".join(
            "%s%s" % ({"picture": "图片", "text": "文字", "shape": "色块", "group": "组合"}.get(s["kind"], s["kind"]),
                      ("「%s」" % s["text"][:10]) if s.get("text") else "") for s in keep))
        if res.get("title") is not None:
            t = next(s for s in rec["shapes"] if s["i"] == res["title"])
            out.append("标题框：「%s」那个位置" % (t.get("text") or "")[:20])
        a = res["area"]
        out.append("内容区域：从页面上方 %d 到 %d（共 %d 高）" % (a["y"], a["y"] + a["h"], a["h"]))
    for x in res["notes"]:
        out.append("说明：" + x)
    for x in res["unsure"]:
        out.append("需要确认：" + x)
    return "\n".join(out)


# ════════════════ 生成 ════════════════

class Builder:
    """在上传文件的包上操作：克隆模板页、删掉旧页，母版 / 主题 / 媒体原样保留"""

    def __init__(self, doc):
        self.doc = doc
        self.ct = doc.text("[Content_Types].xml")
        self.pres = doc.text("ppt/presentation.xml")
        self.prels = doc.text("ppt/_rels/presentation.xml.rels")
        self.new = []  # 新页的包内路径
        self.seq = 1000

    def _free(self, pattern):
        while True:
            self.seq += 1
            name = pattern % self.seq
            if name not in self.doc.files:
                return name

    def clone(self, src_part):
        """复制一页（含关联），备注页不带过去 → 新页路径"""
        d = self.doc
        part = self._free("ppt/slides/slide%d.xml")
        d.files[part] = d.files[src_part]
        d.order.append(part)
        rp = X.Doc._rels_path(src_part)
        if rp in d.files:
            rels = d.text(rp)
            rels = re.sub(r'<Relationship\b[^>]*relationships/notesSlide"[^>]*/>', "", rels)
            d.files[X.Doc._rels_path(part)] = rels.encode("utf-8")
            d.order.append(X.Doc._rels_path(part))
        self.ct = self.ct.replace("</Types>", '<Override PartName="/%s" ContentType="application/vnd.openxmlformats-'
                                              'officedocument.presentationml.slide+xml"/></Types>' % part)
        self.new.append(part)
        return part

    def finish(self):
        """把页序换成新页，删掉旧页（及其备注页）"""
        d = self.doc
        old = list(d.slides)
        ids = [int(v) for v in re.findall(r'<p:sldId\s+id="(\d+)"', self.pres)] or [255]
        nid = max(256, max(ids) + 1)
        rid_nums = [int(v) for v in re.findall(r'Id="rId(\d+)"', self.prels)] or [0]
        rn = max(rid_nums) + 1
        items = []
        for part in self.new:
            rid = "rId%d" % rn
            rn += 1
            self.prels = self.prels.replace("</Relationships>", '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/'
                                            'officeDocument/2006/relationships/slide" Target="%s"/></Relationships>'
                                            % (rid, part.replace("ppt/", "", 1)))
            items.append('<p:sldId id="%d" r:id="%s"/>' % (nid, rid))
            nid += 1
        self.pres = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>|<p:sldIdLst/>", "<p:sldIdLst>%s</p:sldIdLst>" % "".join(items),
                           self.pres, flags=re.S)
        # 旧页：从关系、内容类型、包里删掉
        for part in old:
            tgt = part.replace("ppt/", "", 1)
            self.prels = re.sub(r'<Relationship\b[^>]*Target="/?(?:ppt/)?%s"[^>]*/>' % re.escape(tgt), "", self.prels)
            self.ct = self.ct.replace('<Override PartName="/%s" ContentType="application/vnd.openxmlformats-officedocument.'
                                      'presentationml.slide+xml"/>' % part, "")
            notes = d.rel_of_type(part, "notesSlide")
            for p in (part, X.Doc._rels_path(part), notes, X.Doc._rels_path(notes) if notes else None):
                if p and p in d.files:
                    del d.files[p]
                    d.order.remove(p)
            if notes:
                self.ct = re.sub(r'<Override PartName="/%s"[^>]*/>' % re.escape(notes), "", self.ct)
        d.set_text("[Content_Types].xml", self.ct)
        d.set_text("ppt/presentation.xml", self.pres)
        d.set_text("ppt/_rels/presentation.xml.rels", self.prels)
        d.slides = list(self.new)

    def add_part(self, data, pattern, ctype=None, ext_default=None):
        part = self._free(pattern)
        self.doc.files[part] = data
        self.doc.order.append(part)
        if ctype:
            self.ct = self.ct.replace("</Types>", '<Override PartName="/%s" ContentType="%s"/></Types>' % (part, ctype))
        if ext_default:
            ext, t = ext_default
            if ('Extension="%s"' % ext) not in self.ct and ('Extension="%s"' % ext.upper()) not in self.ct:
                self.ct = self.ct.replace("</Types>", '<Default Extension="%s" ContentType="%s"/></Types>' % (ext, t))
        return part

    def add_rel(self, slide_part, rtype, target_part):
        rp = X.Doc._rels_path(slide_part)
        d = self.doc
        if rp not in d.files:
            d.files[rp] = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
            d.order.append(rp)
        rels = d.text(rp)
        nums = [int(v) for v in re.findall(r'Id="rId(\d+)"', rels)] or [0]
        rid = "rId%d" % (max(nums) + 1)
        tgt = "../" + target_part.replace("ppt/", "", 1)
        rels = rels.replace("</Relationships>", '<Relationship Id="%s" Type="%s" Target="%s"/></Relationships>' % (rid, rtype, tgt))
        d.set_text(rp, rels)
        return rid


def _remove_shapes(xml, idxs):
    spans = X.tree_children(xml)
    for i in sorted(idxs, reverse=True):
        if i < len(spans):
            a, b, _ = spans[i]
            xml = xml[:a] + xml[b:]
    return xml


def _set_shape_text(doc, part, rec, i, text):
    xml = doc.text(part)
    spans = X.tree_children(xml)
    s = next(x for x in rec["shapes"] if x["i"] == i)
    a, b, _ = spans[i]
    sx = xml[a:b]
    sz, warn = X._fit(doc, dict(s, autogrow="<a:spAutoFit" in sx), text)
    new = X._replace_body(sx, text, sz)
    if new is None:
        return "不是文本框"
    doc.set_text(part, xml[:a] + new + xml[b:])
    return warn


def _cover_slots(rec, H):
    ts = [s for s in rec["shapes"] if s["kind"] == "text" and "box" in s]
    filled = [s for s in ts if (s.get("text") or "").strip()]
    title = _biggest_text(filled) or _biggest_text(ts)
    rest = sorted([s for s in filled if s is not title], key=lambda s: -(s.get("size") or 18))
    # 副标题：紧挨在标题下面的那一行（离得远的是模板自带的口号，保留不动）
    sub = next((s for s in rest if title and 0 <= s["box"][1] - (title["box"][1] + title["box"][3]) < 160
                and not re.search(r"\d{4}|年|月", s["text"])), None)
    date = next((s for s in rest if re.search(r"20\d\d|\d{4}\s*年|年\s*\d{1,2}\s*月", s["text"])), None)
    return title, sub, date


def build(upload, deck, out_path=None, options=None):
    """upload：上传的 pptx（路径或字节）；deck：内容（同 myppt 的 deck JSON）→ (pptx 字节, 报告行)"""
    from myppt import enrich as E
    from . import tokens, measure, styles as STY
    from .render import design_page, draw_tree, _pre
    from .engine import api as PA, render as PR
    options = dict(options or {})
    doc = X.Doc(upload)
    inv = X.inventory(doc)
    ana = options.get("analysis") or analyze(doc, inv)
    report = []
    deck = E.clean(deck)
    raw, lays = _pre(deck.get("pages") or [p for c in deck.get("chapters") or [] for p in c.get("pages") or []])
    pages, errors = PA.prepare({"pages": raw})
    if errors:
        raise PA.DeckError(errors)
    for p, lay in zip(pages, lays):
        if lay:
            p["layout"] = lay
    b = Builder(doc)
    th = doc.theme
    cn = (th.get("minor") or {}).get("ea") or "微软雅黑"
    latin = (th.get("minor") or {}).get("latin")
    cn = "微软雅黑" if cn.startswith("+") else cn
    latin = None if (not latin or latin.startswith("+")) else latin
    PR.K.FONT, PR.K.LATIN, PR.K.FONT_HEI = cn, latin, cn
    PR.K.icons_on = True
    measure.set_fonts(cn, latin)
    STY.use(options.get("style") or "corporate")
    saved = dict(tokens.AREA)
    prev_sig, hist = None, []
    chapters = [p for p in pages if p.get("type") == "chapter"]
    ch_no = 0
    try:
        for pi, page in enumerate(pages, 1):
            t = page.get("type")
            src = {"cover": ana["cover"], "toc": ana["toc"], "chapter": ana["chapter"], "end": ana["end"]}.get(t, ana["content"])
            if src is None:
                if t in ("toc", "chapter"):
                    report.append("第 %d 页（%s）：模板里没有这类页，跳过" % (pi, {"toc": "目录", "chapter": "章节页"}[t]))
                    continue
                if t == "end":
                    report.append("第 %d 页（封底）：模板里没有封底，跳过" % pi)
                    continue
                src = ana["content"]
            if src is None:
                report.append("第 %d 页：模板里没有可用的内容页，跳过" % pi)
                continue
            rec = inv[src]
            part = b.clone(rec["part"])
            if t == "cover":
                title, sub, date = _cover_slots(rec, doc.page_h)
                if title is not None:
                    w = _set_shape_text(doc, part, rec, title["i"], page.get("title") or "")
                    report.append("第 %d 页（封面）：标题换成「%s」%s" % (pi, page.get("title"), ("（%s）" % w) if w else ""))
                if sub is not None and page.get("subtitle"):
                    _set_shape_text(doc, part, rec, sub["i"], page["subtitle"])
                elif page.get("subtitle"):
                    report.append("第 %d 页（封面）：模板封面没有副标题位置，副标题「%s」没放" % (pi, page["subtitle"]))
                if date is not None and (page.get("date") or page.get("org")):
                    _set_shape_text(doc, part, rec, date["i"], " ".join(x for x in (page.get("org"), page.get("date")) if x))
            elif t == "end":
                report.append("第 %d 页（封底）：照模板原样" % pi)
            elif t == "chapter":
                ch_no += 1
                ts = [s for s in rec["shapes"] if s["kind"] == "text" and (s.get("text") or "").strip()]
                num = next((s for s in ts if DIGIT_RE.match(s["text"])), None)
                name = _biggest_text([s for s in ts if s is not num])
                if num is not None:
                    _set_shape_text(doc, part, rec, num["i"], re.sub(r"\d+", "%02d" % ch_no if len(re.sub(r"\D", "", num["text"])) == 2
                                                                     else str(ch_no), num["text"], count=1))
                if name is not None:
                    _set_shape_text(doc, part, rec, name["i"], page.get("title") or "")
                report.append("第 %d 页（章节页）：%s" % (pi, page.get("title")))
            elif t == "toc":
                _fill_toc(doc, part, rec, [c.get("title") or "" for c in chapters] or (page.get("items") or []), report, pi)
            else:
                _content_page(doc, b, part, rec, ana, page, pi, report, (prev_sig, hist))
                prev_sig = page.get("_sig")
                if page.get("_fam"):
                    hist.append(page["_fam"])
    finally:
        tokens.AREA.clear()
        tokens.AREA.update(saved)
    b.finish()
    data = doc.save(out_path)
    return data, report


def _fill_toc(doc, part, rec, items, report, pi):
    """目录页：一样大小、左对齐排成一列的文本框是条目；序号框跟着行走。条目比格子多就只填前面的并提示"""
    ts = [s for s in rec["shapes"] if s["kind"] == "text" and "box" in s]
    groups = {}
    for s in ts:
        if DIGIT_RE.match(s.get("text") or "") or TOC_RE.search(s.get("text") or ""):
            continue
        key = (round(s["box"][0] / 30), round(s["box"][2] / 30), round(s["box"][3] / 20))
        groups.setdefault(key, []).append(s)
    rows = max(groups.values(), key=len) if groups else []
    rows = sorted([s for s in rows if (s.get("text") or "").strip()], key=lambda s: s["box"][1])
    if len(rows) < 2:
        report.append("第 %d 页（目录）：没认出目录条目，照模板原样" % pi)
        return
    for s, txt in zip(rows, items):
        _set_shape_text(doc, part, rec, s["i"], txt)
    if len(items) > len(rows):
        report.append("第 %d 页（目录）：模板只有 %d 行，后面 %d 个章节没放进目录" % (pi, len(rows), len(items) - len(rows)))
    elif len(items) < len(rows):
        # 多出来的行：把这一行（条目所在高度带）上的元素都删掉
        xml = doc.text(part)
        kill = []
        for s in rows[len(items):]:
            y0, y1 = s["box"][1] - 30, s["box"][1] + s["box"][3] + 30
            for o in rec["shapes"]:
                if "box" in o and o["box"][1] >= y0 and o["box"][1] + o["box"][3] <= y1 and o["box"][3] < 260:
                    kill.append(o["i"])
        doc.set_text(part, _remove_shapes(xml, set(kill)))
        report.append("第 %d 页（目录）：%d 个章节，删掉了模板里多余的 %d 行" % (pi, len(items), len(rows) - len(items)))
    else:
        report.append("第 %d 页（目录）：%d 个章节" % (pi, len(items)))


def _content_page(doc, b, part, rec, ana, page, pi, report, ctx):
    from . import tokens
    from .render import design_page, draw_tree
    from .spec import signature, family
    from .engine import render as PR
    from .engine.ooxml.package import Presentation
    xml = doc.text(part)
    drop = [s["i"] for s in rec["shapes"] if s["i"] not in ana["keep"]]
    if ana.get("title") is not None:
        s = next(x for x in rec["shapes"] if x["i"] == ana["title"])
        sx_spans = X.tree_children(xml)
        a, e, _ = sx_spans[s["i"]]
        sx = xml[a:e]
        sz, warn = X.fit_line(doc, s, page.get("title") or "", sx)
        new = X._replace_body(sx, page.get("title") or "", sz)
        if new is not None:
            xml = xml[:a] + new + xml[e:]
        if warn:
            report.append("第 %d 页：%s" % (pi, warn))
    xml = _remove_shapes(xml, drop)
    tokens.AREA.clear()
    tokens.AREA.update(ana["area"])
    from .palette import to_engine_colors
    pal = X.theme_palette(doc, doc.text(rec["part"]))
    font, latin = PR.K.FONT, PR.K.LATIN
    PR.apply_theme({"colors": to_engine_colors(pal)}, {"cn": font, "latin": latin, "hei": font})
    PR.K.CHART_COLORS = [pal["primary"], pal.get("secondary") or pal["accent"], pal["accent"], pal["muted"], pal["line"]]
    PR.K.icons_on = True
    PR.K.page_icons = set()
    prev_sig, hist = ctx
    got = design_page(page, prev_sig, tuple(hist))
    if not got or got[1] is None:
        report.append("第 %d 页：内容排不下，只放了标题（%s）" % (pi, "；".join(got[3]) if got else ""))
        doc.set_text(part, xml)
        return
    how, tree, res, notes = got
    page["_sig"], page["_fam"] = signature(tree), family(tree)

    pres = Presentation(13.333, 13.333 * doc.cy / doc.cx, title="")
    slide = pres.add_slide()
    draw_tree(slide, res, pal, [])
    data = pres.to_bytes()
    frag = _transplant(doc, b, part, data, xml)
    i = X.sptree_end(xml)
    xml = xml[:i] + frag + xml[i:]
    doc.set_text(part, xml)
    report.append("第 %d 页：%s（%s，字号档 %d）" % (pi, page.get("title") or "", how.replace("程序设计:", "版式 "), res["level"]))


_CT = {"chart": "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"}


def _transplant(doc, b, part, data, slide_xml):
    """临时页上画好的形状搬到目标页：编号接着排、图片/图表的关联文件一起搬过来"""
    tmp = zipfile.ZipFile(io.BytesIO(data))
    sx = tmp.read("ppt/slides/slide1.xml").decode("utf-8")
    frag = "".join(sx[a:e] for a, e, _ in X.tree_children(sx))
    rels = {}
    try:
        for r in ET.fromstring(tmp.read("ppt/slides/_rels/slide1.xml.rels")):
            rels[r.get("Id")] = (r.get("Type"), X._join("ppt/slides", r.get("Target")))
    except KeyError:
        pass
    mapping = {}
    for rid in set(re.findall(r'r:(?:embed|id|link)="(rId\d+)"', frag)):
        if rid not in rels:
            continue
        rtype, tpart = rels[rid]
        blob = tmp.read(tpart)
        ext = tpart.rsplit(".", 1)[-1].lower()
        if "/chart" in rtype:
            newp = b.add_part(blob, "ppt/charts/chart%d.xml", _CT["chart"])
            # 图表自带的数据表格
            try:
                crel = tmp.read(X.Doc._rels_path(tpart)).decode("utf-8")
                for m in re.finditer(r'Target="([^"]+)"', crel):
                    src = X._join(tpart.rsplit("/", 1)[0], m.group(1))
                    eb = b.add_part(tmp.read(src), "ppt/embeddings/Microsoft_Excel_Worksheet%d.xlsx", None,
                                    ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                    crel = crel.replace(m.group(1), "../embeddings/" + eb.rsplit("/", 1)[1])
                doc.files[X.Doc._rels_path(newp)] = crel.encode("utf-8")
                doc.order.append(X.Doc._rels_path(newp))
            except KeyError:
                pass
        else:
            mt = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "svg": "image/svg+xml",
                  "emf": "image/x-emf"}.get(ext, "application/octet-stream")
            newp = b.add_part(blob, "ppt/media/lab%d." + ext, None, (ext, mt))
        mapping[rid] = b.add_rel(part, rtype, newp)
    if mapping:
        frag = re.sub(r'(r:(?:embed|id|link)=")(rId\d+)(")', lambda m: m.group(1) + mapping.get(m.group(2), m.group(2)) + m.group(3), frag)
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
    return re.sub(r'<p:cNvPr\s+id="\d+"', renum, frag)


def main(argv=None):
    """python -m myppt.reuse analyze 模板.pptx
       python -m myppt.reuse build 模板.pptx deck.json 输出.pptx"""
    import json
    import sys
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 2 and a[0] == "analyze":
        d = X.Doc(a[1])
        print(describe_analysis(d, analyze(d)))
        return 0
    if len(a) >= 4 and a[0] == "build":
        deck = json.load(open(a[2], encoding="utf-8"))
        _, rep = build(a[1], deck, a[3], deck.get("options"))
        print("\n".join(rep))
        print("已保存 %s" % a[3])
        return 0
    print(main.__doc__)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
