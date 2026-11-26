"""固定部件模板：主题、母版、空白版式、演示文稿属性等。"""
from .util import esc

NS_P = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def theme_xml(colors, font="微软雅黑", font_hei="黑体", name="pptlab"):
    c = colors
    f = esc(font)
    fh = esc(font_hei)
    return XML_HEAD + (
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="%s"><a:themeElements>'
        '<a:clrScheme name="%s"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
        '<a:dk2><a:srgbClr val="%s"/></a:dk2><a:lt2><a:srgbClr val="%s"/></a:lt2>'
        '<a:accent1><a:srgbClr val="%s"/></a:accent1><a:accent2><a:srgbClr val="%s"/></a:accent2><a:accent3><a:srgbClr val="%s"/></a:accent3>'
        '<a:accent4><a:srgbClr val="%s"/></a:accent4><a:accent5><a:srgbClr val="%s"/></a:accent5><a:accent6><a:srgbClr val="%s"/></a:accent6>'
        '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
        '<a:fontScheme name="%s"><a:majorFont><a:latin typeface="%s"/><a:ea typeface="%s"/><a:cs typeface=""/></a:majorFont>'
        '<a:minorFont><a:latin typeface="%s"/><a:ea typeface="%s"/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
        '<a:fmtScheme name="Office"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:tint val="50000"/></a:schemeClr></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:shade val="80000"/></a:schemeClr></a:solidFill></a:fillStyleLst>'
        '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
        '<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
        '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
        '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/></a:schemeClr></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"><a:shade val="90000"/></a:schemeClr></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements>'
        '<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>'
    ) % (esc(name), esc(name), c["deep"], c["soft"], c["blue"], c["primary"], c["green"], c["accent"], c["gray"], c["mid"],
         esc(name), fh, fh, f, f)


def master_xml(n_layouts=1):
    return XML_HEAD + (
        '<p:sldMaster %s><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        '</p:spTree></p:cSld>'
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst>%s</p:sldLayoutIdLst>'
        '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="4400"><a:latin typeface="+mj-lt"/><a:ea typeface="+mj-ea"/></a:defRPr></a:lvl1pPr></p:titleStyle>'
        '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2000"><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/></a:defRPr></a:lvl1pPr></p:bodyStyle>'
        '<p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/></a:defRPr></a:lvl1pPr></p:otherStyle></p:txStyles>'
        '</p:sldMaster>'
    ) % (NS_P, "".join('<p:sldLayoutId id="%d" r:id="rId%d"/>' % (2147483649 + i, i + 1) for i in range(n_layouts)))


def layout_xml(name="空白", items="", bg="", ltype="blank"):
    return XML_HEAD + (
        '<p:sldLayout %s type="%s" preserve="1"><p:cSld name="%s">%s<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        '%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    ) % (NS_P, ltype, esc(name), bg, items)


def rels_xml(rels):
    out = [XML_HEAD, '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for rid, t, target in rels:
        out.append('<Relationship Id="%s" Type="%s" Target="%s"/>' % (rid, t, esc(target)))
    out.append("</Relationships>")
    return "".join(out)


R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def app_xml(nslides):
    return XML_HEAD + (
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>pptlab</Application><PresentationFormat>宽屏</PresentationFormat><Slides>%d</Slides><AppVersion>16.0000</AppVersion></Properties>'
    ) % nslides


def core_xml(title, created):
    return XML_HEAD + (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>%s</dc:title><dc:creator>pptlab</dc:creator><cp:lastModifiedBy>pptlab</cp:lastModifiedBy><cp:revision>1</cp:revision>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
        '</cp:coreProperties>'
    ) % (esc(title), created, created)


PRES_PROPS = XML_HEAD + '<p:presentationPr %s/>' % NS_P
VIEW_PROPS = XML_HEAD + ('<p:viewPr %s><p:normalViewPr><p:restoredLeft sz="15620"/><p:restoredTop sz="94660"/></p:normalViewPr>'
                         '<p:gridSpacing cx="76200" cy="76200"/></p:viewPr>') % NS_P
TABLE_STYLES = XML_HEAD + '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>'
