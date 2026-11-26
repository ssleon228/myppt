"""演示文稿包：收集幻灯片、媒体、图表，写成 .pptx（zip）。"""
import datetime
import hashlib
import io
import os
import zipfile

from . import parts
from .images import sniff, MIME
from .slide import Slide
from .util import EMU, esc

CT_SLIDE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"


class Presentation:
    def __init__(self, width_in=13.333, height_in=7.5, title="", theme_colors=None, font="微软雅黑", font_hei="黑体"):
        self.width = width_in
        self.height = height_in
        self.title = title
        self.slides = []
        self.media = {}  # sha1 → (name, data, ext, w, h)
        self.media_by_path = {}
        self.charts = []  # (name, xml, xlsx_bytes)
        self.theme_colors = theme_colors or {
            "primary": "2563EB", "mid": "1D4ED8", "blue": "1E40AF", "accent": "059669", "green": "34D399",
            "deep": "1E293B", "text": "334155", "gray": "64748B", "line": "E2E8F0", "soft": "F1F5F9"}
        self.font = font
        self.font_hei = font_hei
        self.show_master_sp = True
        self.warnings = []
        # 中文字体 → 西文字体（同一个 run 的 latin 槽位用西文字体，如 中文黑体 → 某种西文字体）
        self.latin_fonts = {}
        # 程序生成的版式：[{name, type, canvas(Slide), title_ph, extra}]，空则只有一个空白版式
        self.layouts = []

    def add_layout(self, name, ltype="obj", title_ph="title"):
        """新建一个版式画布：在它上面画图形，导出时变成 slideLayout"""
        from .slide import Slide
        c = Slide(self, 0)
        rid, _, _, ex = c.rels[0]
        c.rels[0] = (rid, parts.R + "slideMaster", "../slideMasters/slideMaster1.xml", ex)
        self.layouts.append({"name": name, "type": ltype, "canvas": c, "title_ph": title_ph, "extra": []})
        return len(self.layouts), c

    def add_slide(self):
        s = Slide(self, len(self.slides) + 1)
        self.slides.append(s)
        return s

    def add_media(self, path=None, data=None):
        """登记图片，返回 (文件名, 宽px, 高px)；读不到返回 None"""
        if data is None:
            if not path:
                return None
            key = os.path.abspath(path)
            if key in self.media_by_path:
                return self.media_by_path[key]
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError as e:
                self.warnings.append("图片读取失败：%s（%s）" % (path, e))
                return None
        else:
            key = None
        ext, w, h = sniff(data)
        if not ext:
            self.warnings.append("无法识别的图片格式：%s" % (path or "<data>"))
            return None
        digest = hashlib.sha1(data).hexdigest()
        if digest in self.media:
            name, _, _, w, h = self.media[digest]
        else:
            name = "image%d.%s" % (len(self.media) + 1, "jpeg" if ext == "jpeg" else ext)
            self.media[digest] = (name, data, ext, w, h)
        res = (name, w, h)
        if key:
            self.media_by_path[key] = res
        return res

    def add_chart(self, xml, xlsx=None):
        name = "chart%d.xml" % (len(self.charts) + 1)
        self.charts.append((name, xml, xlsx))
        return name

    # ── 输出 ──
    def _layout_parts(self):
        """→ [(layout xml, rels xml)]；最后总是附一个空白版式"""
        from .. import layouts as L
        out = []
        for lay in self.layouts:
            c = lay["canvas"]
            items = L.canvas_to_layout_items(c.items, lay["title_ph"]) + list(lay["extra"])
            out.append((parts.layout_xml(lay["name"], "".join(items), c.bg_xml(), lay["type"]), c.rels_xml()))
        out.append((parts.layout_xml(), parts.rels_xml([
            ("rId1", parts.R + "slideMaster", "../slideMasters/slideMaster1.xml")])))
        return out

    def to_bytes(self):
        buf = io.BytesIO()
        z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
        files = {}
        R = parts.R
        n = len(self.slides)
        # 内容类型
        defaults = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml",
                    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        for name, data, ext, w, h in self.media.values():
            defaults[name.rsplit(".", 1)[1]] = MIME.get(ext, "application/octet-stream")
        overrides = {
            "/ppt/presentation.xml": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
            "/ppt/slideMasters/slideMaster1.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
            "/ppt/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
            "/ppt/presProps.xml": "application/vnd.openxmlformats-officedocument.presentationml.presProps+xml",
            "/ppt/viewProps.xml": "application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml",
            "/ppt/tableStyles.xml": "application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml",
            "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
            "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        }
        layouts = self._layout_parts()
        for i in range(len(layouts)):
            overrides["/ppt/slideLayouts/slideLayout%d.xml" % (i + 1)] = \
                "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
        for i in range(n):
            overrides["/ppt/slides/slide%d.xml" % (i + 1)] = CT_SLIDE
        for name, _, _ in self.charts:
            overrides["/ppt/charts/" + name] = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
        ct = [parts.XML_HEAD, '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">']
        for ext, t in sorted(defaults.items()):
            ct.append('<Default Extension="%s" ContentType="%s"/>' % (ext, t))
        for pn, t in overrides.items():
            ct.append('<Override PartName="%s" ContentType="%s"/>' % (pn, t))
        ct.append("</Types>")
        files["[Content_Types].xml"] = "".join(ct)
        files["_rels/.rels"] = parts.rels_xml([
            ("rId1", R + "officeDocument", "ppt/presentation.xml"),
            ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
            ("rId3", R + "extended-properties", "docProps/app.xml")])
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        files["docProps/core.xml"] = parts.core_xml(self.title, now)
        files["docProps/app.xml"] = parts.app_xml(n)
        # presentation
        prels = [("rId1", R + "slideMaster", "slideMasters/slideMaster1.xml")]
        sld_ids = []
        for i in range(n):
            rid = "rId%d" % (i + 2)
            prels.append((rid, R + "slide", "slides/slide%d.xml" % (i + 1)))
            sld_ids.append('<p:sldId id="%d" r:id="%s"/>' % (256 + i, rid))
        k = n + 2
        prels += [("rId%d" % k, R + "presProps", "presProps.xml"), ("rId%d" % (k + 1), R + "viewProps", "viewProps.xml"),
                  ("rId%d" % (k + 2), R + "theme", "theme/theme1.xml"), ("rId%d" % (k + 3), R + "tableStyles", "tableStyles.xml")]
        files["ppt/_rels/presentation.xml.rels"] = parts.rels_xml(prels)
        cx = int(round(self.width * EMU))
        cy = int(round(self.height * EMU))
        files["ppt/presentation.xml"] = parts.XML_HEAD + (
            '<p:presentation %s saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            '<p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/>'
            '<p:defaultTextStyle><a:lvl1pPr><a:defRPr lang="zh-CN"/></a:lvl1pPr></p:defaultTextStyle></p:presentation>'
        ) % (parts.NS_P, "".join(sld_ids), cx, cy)
        files["ppt/presProps.xml"] = parts.PRES_PROPS
        files["ppt/viewProps.xml"] = parts.VIEW_PROPS
        files["ppt/tableStyles.xml"] = parts.TABLE_STYLES
        th = parts.theme_xml(self.theme_colors, self.font, self.font_hei)
        for f in (self.font, self.font_hei):
            lat = self.latin_fonts.get(f)
            if lat:
                th = th.replace('<a:latin typeface="%s"/>' % parts.esc(f), '<a:latin typeface="%s"/>' % parts.esc(lat))
        files["ppt/theme/theme1.xml"] = th
        nl = len(layouts)
        files["ppt/slideMasters/slideMaster1.xml"] = parts.master_xml(nl)
        files["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = parts.rels_xml(
            [("rId%d" % (i + 1), R + "slideLayout", "../slideLayouts/slideLayout%d.xml" % (i + 1)) for i in range(nl)] +
            [("rId%d" % (nl + 1), R + "theme", "../theme/theme1.xml")])
        for i, (xml, rels) in enumerate(layouts):
            files["ppt/slideLayouts/slideLayout%d.xml" % (i + 1)] = xml
            files["ppt/slideLayouts/_rels/slideLayout%d.xml.rels" % (i + 1)] = rels
        from .. import layouts as L
        for s in self.slides:
            xml = s.to_xml(self.show_master_sp)
            if s.title_ph:
                xml = L.mark_slide_title(xml, s.title_ph)
            files["ppt/slides/slide%d.xml" % s.index] = xml
            files["ppt/slides/_rels/slide%d.xml.rels" % s.index] = s.rels_xml()
        for name, xml, xlsx in self.charts:
            files["ppt/charts/" + name] = xml
            if xlsx:
                xn = name.replace("chart", "chartdata").replace(".xml", ".xlsx")
                files["ppt/embeddings/" + xn] = xlsx
                files["ppt/charts/_rels/%s.rels" % name] = parts.rels_xml([
                    ("rId1", R + "package", "../embeddings/" + xn)])
        for name, data, ext, w, h in self.media.values():
            files["ppt/media/" + name] = data
        for fn in ["[Content_Types].xml", "_rels/.rels"] + [f for f in files if f not in ("[Content_Types].xml", "_rels/.rels")]:
            v = files[fn]
            z.writestr(fn, v.encode("utf-8") if isinstance(v, str) else v)
        z.close()
        return buf.getvalue()
