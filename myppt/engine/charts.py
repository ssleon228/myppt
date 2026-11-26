"""原生图表（PowerPoint 可编辑）：柱/条形、折线、环形、雷达，附内嵌 xlsx 数据（可「编辑数据」）。

样式口径沿用旧版（pptxgenjs 参数），并修正旧版两个问题：
  · 数据标签格式固定 #,##0 会把 3.5 显示成 4 → 按数据小数位自动选格式；
  · 图表文字用 Arial → 用模板中/西文字体。
环形图 <4% 的小扇区标签自动隐藏（避免叠印）。
"""
import io
import math
import zipfile

from .ooxml.util import esc, hexcolor

NS = ('xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def FS(px):
    return (px / 2.0) * (1.18 if px <= 30 else 1)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _decimals(vals):
    d = 0
    for v in vals:
        s = ("%.6f" % abs(v)).rstrip("0").rstrip(".")
        if "." in s:
            d = max(d, len(s.split(".")[1]))
    return min(d, 2)


def _fmt_code(vals):
    d = _decimals(vals)
    return "#,##0" if d == 0 else "#,##0." + "0" * d


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _font(K, sz, color, bold=False):
    latin = K.LATIN or K.FONT
    return ('<a:defRPr sz="%d" b="%d"><a:solidFill><a:srgbClr val="%s"/></a:solidFill>'
            '<a:latin typeface="%s"/><a:ea typeface="%s"/><a:cs typeface="%s"/></a:defRPr>') % (
        int(round(sz * 100)), 1 if bold else 0, hexcolor(color), esc(latin), esc(K.FONT), esc(latin))


def _txpr(K, sz, color, bold=False):
    return ('<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr>%s</a:pPr><a:endParaRPr lang="zh-CN"/></a:p></c:txPr>'
            % _font(K, sz, color, bold))


def _ln(color, w_pt, none=False):
    if none:
        return "<a:ln><a:noFill/></a:ln>"
    return '<a:ln w="%d" cap="flat"><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:prstDash val="solid"/><a:round/></a:ln>' % (
        int(round(w_pt * 12700)), hexcolor(color))


def _str_cache(ref, vals):
    pts = "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (i, esc(v)) for i, v in enumerate(vals))
    return '<c:strRef><c:f>%s</c:f><c:strCache><c:ptCount val="%d"/>%s</c:strCache></c:strRef>' % (ref, len(vals), pts)


def _num_cache(ref, vals, code):
    pts = "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (i, repr(float(v)) if v != int(v) else int(v))
                  for i, v in enumerate(vals))
    return ('<c:numRef><c:f>%s</c:f><c:numCache><c:formatCode>%s</c:formatCode><c:ptCount val="%d"/>%s</c:numCache></c:numRef>'
            % (ref, esc(code), len(vals), pts))


def _dlbls(K, code, sz, color, pos=None, val=True, pct=False, deletes=()):
    dels = "".join('<c:dLbl><c:idx val="%d"/><c:delete val="1"/></c:dLbl>' % i for i in deletes)
    p = '<c:dLblPos val="%s"/>' % pos if pos else ""
    return ('<c:dLbls>%s<c:numFmt formatCode="%s" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>%s%s'
            '<c:showLegendKey val="0"/><c:showVal val="%d"/><c:showCatName val="0"/><c:showSerName val="0"/>'
            '<c:showPercent val="%d"/><c:showBubbleSize val="0"/><c:showLeaderLines val="0"/></c:dLbls>') % (
        dels, esc("0%" if pct else code), _txpr(K, sz, color), p, 1 if val else 0, 1 if pct else 0)


def _title(K, C, text):
    if not text:
        return '<c:autoTitleDeleted val="1"/>'
    return ('<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr>%s</a:pPr><a:r><a:rPr lang="zh-CN" sz="%d" b="1">'
            '<a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:latin typeface="%s"/><a:ea typeface="%s"/></a:rPr><a:t>%s</a:t></a:r></a:p>'
            '</c:rich></c:tx><c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>') % (
        _font(K, FS(20), C.deep, True), int(round(FS(20) * 100)), hexcolor(C.deep), esc(K.LATIN or K.FONT), esc(K.FONT),
        esc(text))


def _legend(K, C, show):
    if not show:
        return ""
    return '<c:legend><c:legendPos val="b"/><c:overlay val="0"/>%s</c:legend>' % _txpr(K, FS(18), C.gray)


def _axes(K, C, cat_pos, val_pos, code, horizontal=False):
    cat = ('<c:catAx><c:axId val="111"/><c:scaling><c:orientation val="%s"/></c:scaling><c:delete val="0"/>'
           '<c:axPos val="%s"/><c:numFmt formatCode="General" sourceLinked="1"/><c:majorTickMark val="none"/>'
           '<c:minorTickMark val="none"/><c:tickLblPos val="low"/><c:spPr>%s</c:spPr>%s<c:crossAx val="222"/>'
           '<c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/>'
           '<c:noMultiLvlLbl val="1"/></c:catAx>') % (
        "maxMin" if horizontal else "minMax", cat_pos, _ln(C.gray, 1), _txpr(K, FS(18), C.gray))
    val = ('<c:valAx><c:axId val="222"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
           '<c:axPos val="%s"/><c:majorGridlines><c:spPr>%s</c:spPr></c:majorGridlines>'
           '<c:numFmt formatCode="%s" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
           '<c:tickLblPos val="nextTo"/><c:spPr>%s</c:spPr>%s<c:crossAx val="111"/><c:crosses val="%s"/>'
           '<c:crossBetween val="between"/></c:valAx>') % (
        val_pos, _ln(C.line, 0.75), esc(code), _ln(C.line, 0.75, none=True), _txpr(K, FS(16), C.gray),
        "max" if horizontal else "autoZero")
    return cat + val


def _space(plot, title, legend):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<c:chartSpace %s><c:date1904 val="0"/>'
            '<c:lang val="zh-CN"/><c:roundedCorners val="0"/><c:chart>%s<c:plotArea><c:layout/>%s'
            '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr></c:plotArea>%s<c:plotVisOnly val="1"/>'
            '<c:dispBlanksAs val="gap"/></c:chart><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
            '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr lang="zh-CN"/></a:pPr><a:endParaRPr lang="zh-CN"/></a:p></c:txPr>'
            '<c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData></c:chartSpace>') % (NS, title, plot, legend)


def chart_xml(chart, K, C):
    """→ (chart xml, xlsx bytes)"""
    kind = chart.kind or "bar"
    cats = [str(c) for c in (chart.categories or [])]
    series = [s for s in (chart.series or []) if s is not None]
    if not series:
        series = [type(chart)(name="数据", values=[0] * len(cats))]
    n = len(cats)
    data = []
    for s in series:
        vals = [_num(v) for v in (s.get("values") or [])][:n]
        vals += [0.0] * (n - len(vals))
        data.append((str(s.name or "数据"), vals))
    allv = [v for _, vs in data for v in vs]
    code = _fmt_code(allv)
    colors = list(K.CHART_COLORS)
    cat_ref = "Sheet1!$A$2:$A$%d" % (n + 1)

    def ser_head(i, name, color_xml):
        return ('<c:ser><c:idx val="%d"/><c:order val="%d"/><c:tx>%s</c:tx>%s' %
                (i, i, _str_cache("Sheet1!$%s$1" % _col(i + 1), [name]), color_xml))

    def cat_val(i, vals):
        return '<c:cat>%s</c:cat><c:val>%s</c:val>' % (
            _str_cache(cat_ref, cats), _num_cache("Sheet1!$%s$2:$%s$%d" % (_col(i + 1), _col(i + 1), n + 1), vals, code))

    if kind == "pie":
        name, vals = data[0]
        total = sum(vals)
        tiny = [i for i, v in enumerate(vals) if total > 0 and len(vals) >= 2 and v / total < 0.04]
        dpts = "".join('<c:dPt><c:idx val="%d"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill>'
                       '<a:ln w="19050"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:ln></c:spPr></c:dPt>'
                       % (i, hexcolor(colors[i % len(colors)])) for i in range(n))
        ser = ser_head(0, name or "占比", "") + dpts + _dlbls(K, code, FS(18), "FFFFFF", val=False, pct=True,
                                                               deletes=tiny) + cat_val(0, vals) + "</c:ser>"
        plot = ('<c:doughnutChart><c:varyColors val="1"/>%s<c:firstSliceAng val="0"/><c:holeSize val="60"/></c:doughnutChart>'
                % ser)
        return _space(plot, _title(K, C, chart.title), _legend(K, C, True)), _xlsx(cats, data)
    if kind == "radar":
        sers = ""
        for i, (name, vals) in enumerate(data):
            col = hexcolor(colors[i % len(colors)])
            sp = '<c:spPr><a:ln w="38100" cap="rnd"><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:round/></a:ln></c:spPr>' % col
            mk = ('<c:marker><c:symbol val="circle"/><c:size val="7"/><c:spPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill>'
                  '<a:ln><a:noFill/></a:ln></c:spPr></c:marker>' % col)
            sers += ser_head(i, name, sp + mk) + cat_val(i, vals) + "</c:ser>"
        plot = ('<c:radarChart><c:radarStyle val="marker"/><c:varyColors val="0"/>%s<c:axId val="111"/><c:axId val="222"/></c:radarChart>'
                % sers)
        axes = ('<c:catAx><c:axId val="111"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
                '<c:axPos val="b"/><c:majorGridlines><c:spPr>%s</c:spPr></c:majorGridlines><c:numFmt formatCode="General" sourceLinked="1"/>'
                '<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:spPr>%s</c:spPr>%s'
                '<c:crossAx val="222"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>'
                '<c:valAx><c:axId val="222"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="l"/>'
                '<c:majorGridlines><c:spPr>%s</c:spPr></c:majorGridlines><c:numFmt formatCode="%s" sourceLinked="0"/>'
                '<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:spPr>%s</c:spPr>%s'
                '<c:crossAx val="111"/><c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx>') % (
            _ln(C.line, 0.75), _ln(C.line, 0.75), _txpr(K, FS(18), C.gray), _ln(C.line, 0.75), esc(code),
            _ln(C.line, 0.75, True), _txpr(K, FS(16), C.gray))
        return _space(plot + axes, _title(K, C, chart.title), _legend(K, C, len(data) > 1)), _xlsx(cats, data)
    if kind == "line":
        sers = ""
        for i, (name, vals) in enumerate(data):
            col = hexcolor(colors[i % len(colors)])
            sp = '<c:spPr><a:ln w="38100" cap="rnd"><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:round/></a:ln></c:spPr>' % col
            mk = ('<c:marker><c:symbol val="circle"/><c:size val="8"/><c:spPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
                  '<a:ln w="25400"><a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:ln></c:spPr></c:marker>' % col)
            sers += (ser_head(i, name, sp + mk) + _dlbls(K, code, FS(18), C.text, pos="t") + cat_val(i, vals) +
                     '<c:smooth val="0"/></c:ser>')
        plot = ('<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>%s<c:marker val="1"/>'
                '<c:axId val="111"/><c:axId val="222"/></c:lineChart>' % sers) + _axes(K, C, "b", "l", code)
        return _space(plot, _title(K, C, chart.title), _legend(K, C, len(data) > 1)), _xlsx(cats, data)
    # bar / barH
    horizontal = kind == "barH"
    sers = ""
    for i, (name, vals) in enumerate(data):
        col = hexcolor(C.blue if len(data) == 1 else colors[i % len(colors)])
        sp = '<c:spPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr>' % col
        sers += (ser_head(i, name, sp) + '<c:invertIfNegative val="0"/>' + _dlbls(K, code, FS(18), C.text, pos="outEnd") +
                 cat_val(i, vals) + "</c:ser>")
    plot = ('<c:barChart><c:barDir val="%s"/><c:grouping val="clustered"/><c:varyColors val="0"/>%s'
            '<c:gapWidth val="60"/><c:overlap val="%d"/><c:axId val="111"/><c:axId val="222"/></c:barChart>'
            % ("bar" if horizontal else "col", sers, 0 if len(data) == 1 else -10)) + \
        _axes(K, C, "l" if horizontal else "b", "b" if horizontal else "l", code, horizontal)
    return _space(plot, _title(K, C, chart.title), _legend(K, C, len(data) > 1)), _xlsx(cats, data)


def _xlsx(cats, data):
    """最小合法 xlsx（内联字符串），供 PowerPoint「编辑数据」"""
    rows = []
    head = ['<c r="A1" t="inlineStr"><is><t></t></is></c>'] + [
        '<c r="%s1" t="inlineStr"><is><t>%s</t></is></c>' % (_col(i + 1), esc(name)) for i, (name, _) in enumerate(data)]
    rows.append('<row r="1">%s</row>' % "".join(head))
    for ri, cat in enumerate(cats):
        r = ri + 2
        cells = ['<c r="A%d" t="inlineStr"><is><t>%s</t></is></c>' % (r, esc(cat))]
        for ci, (_, vals) in enumerate(data):
            cells.append('<c r="%s%d"><v>%s</v></c>' % (_col(ci + 1), r, repr(vals[ri])))
        rows.append('<row r="%d">%s</row>' % (r, "".join(cells)))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>%s</sheetData></worksheet>' % "".join(rows))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                               '<Default Extension="xml" ContentType="application/xml"/>'
                               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                               '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def add_native_chart(slide, chart, box, K, C):
    xml, xlsx = chart_xml(chart, K, C)
    name = slide.pres.add_chart(xml, xlsx)
    slide.add_chart_xml(name, x=box["x"] / 144.0, y=box["y"] / 144.0, w=box["w"] / 144.0, h=box["h"] / 144.0)
