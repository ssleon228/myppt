"""程序自己生成的母版版式（不再搬运模板 pptx 里的母版）。

做法：用渲染页面的同一套函数（封面 / 内容页 Banner / 章节页 / 封底）在「画布」上画一遍，
把画出来的图形变成版式（slideLayout）：
  · 名为 Title 的文本框 → 标题占位符（封面为 ctrTitle），保留字体、字号、颜色和位置；
  · 其他文字（副标题、页码、来源行等示例文字）去掉，图形和图片原样保留；
  · 内容页版式另加一个正文占位符，位置就是 Banner 以下的可排版区。
这样用户在 PowerPoint 里「新建幻灯片」时能直接选到带模板外观的版式，大纲视图也认得每页标题。

成品页本身已经把模板外观画好，所以每页 showMasterSp="0"（隐藏版式图形），不会画两遍。
"""
import re

PROMPT = {"title": "单击此处编辑标题", "ctrTitle": "单击此处编辑标题", "body": "单击此处编辑文本"}

_SP = re.compile(r"<p:sp>[\s\S]*?</p:sp>")


def _is_title(sp):
    return 'name="Title"' in sp.split("</p:nvSpPr>")[0]


def _is_text_only(sp):
    """文本框（无填充的纯文字）"""
    return '<p:cNvSpPr txBox="1"/>' in sp


def _strip_text(sp):
    """有文字的形状（如带填充的胶囊标签）：保留形状，清掉文字"""
    return re.sub(r"<p:txBody>[\s\S]*</p:txBody>",
                  '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="zh-CN"/></a:p></p:txBody>', sp)


def _to_placeholder(sp, ph_type, sid):
    """标题文本框 → 占位符：位置/格式不变，文字换成提示语，只留第一段第一个 run 的格式"""
    ph = '<p:ph type="%s"/>' % ph_type
    sp = re.sub(r'<p:cNvPr id="\d+" name="[^"]*"', '<p:cNvPr id="%d" name="标题 %d"' % (sid, sid), sp, count=1)
    sp = re.sub(r"<p:nvPr>\s*</p:nvPr>|<p:nvPr/>", "<p:nvPr>%s</p:nvPr>" % ph, sp, count=1)
    sp = sp.replace('<p:cNvSpPr txBox="1"/>', '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>', 1)
    sp = sp.replace("<p:cNvSpPr/>", '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>', 1)
    m = re.search(r"(<p:txBody>[\s\S]*?<a:lstStyle/>)([\s\S]*)</p:txBody>", sp)
    if m:
        paras = m.group(2)
        ppr = re.search(r"<a:pPr[^>]*/>|<a:pPr[\s\S]*?</a:pPr>", paras)
        rpr = re.search(r"<a:rPr[^>]*/>|<a:rPr[\s\S]*?</a:rPr>", paras)
        p = "<a:p>%s<a:r>%s<a:t>%s</a:t></a:r></a:p>" % (ppr.group(0) if ppr else "", rpr.group(0) if rpr else "",
                                                       PROMPT[ph_type])
        sp = sp[:m.start()] + m.group(1) + p + "</p:txBody>" + sp[m.end():]
    return sp


def body_placeholder(sid, x, y, w, h, font, latin, color, size_pt=20):
    from .ooxml.util import EMU, esc
    lat = esc(latin or font)
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="内容占位符 %d"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm></p:spPr>'
            '<p:txBody><a:bodyPr lIns="91440" tIns="45720" rIns="91440" bIns="45720"><a:normAutofit/></a:bodyPr>'
            '<a:lstStyle><a:lvl1pPr marL="0" indent="0"><a:lnSpc><a:spcPct val="130000"/></a:lnSpc><a:buNone/>'
            '<a:defRPr sz="%d"><a:solidFill><a:srgbClr val="%s"/></a:solidFill>'
            '<a:latin typeface="%s"/><a:ea typeface="%s"/></a:defRPr></a:lvl1pPr></a:lstStyle>'
            '<a:p><a:r><a:rPr lang="zh-CN"/><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>') % (
        sid, sid, int(x * EMU), int(y * EMU), int(w * EMU), int(h * EMU), int(size_pt * 100), color, lat, esc(font),
        PROMPT["body"])


def canvas_to_layout_items(items, title_ph):
    """画布上的图形 → 版式里的图形 + 标题占位符"""
    out = []
    sid = 1000
    for it in items:
        if not it.startswith("<p:sp>"):
            out.append(it)
            continue
        if _is_title(it):
            sid += 1
            out.append(_to_placeholder(it, title_ph, sid))
        elif _is_text_only(it):
            continue
        elif "<a:t>" in it:
            out.append(_strip_text(it))
        else:
            out.append(it)
    return out


def mark_slide_title(xml, ph_type):
    """成品页的标题文本框标成标题占位符（大纲视图、导航、无障碍都认得）。
    占位符会继承版式里的标题格式，所以把内边距、行距、自动调整显式写回，保证外观不变。"""
    ph = '<p:ph type="%s"/>' % ph_type
    done = [False]

    def fix(m):
        sp = m.group(0)
        if done[0] or not _is_title(sp):
            return sp
        done[0] = True
        sp = re.sub(r"<p:nvPr>\s*</p:nvPr>|<p:nvPr/>", "<p:nvPr>%s</p:nvPr>" % ph, sp, count=1)
        sp = sp.replace('<p:cNvSpPr txBox="1"/>', '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>', 1)
        sp = re.sub(r"<a:bodyPr((?![^>]*lIns=)[^>]*?)(/?)>",
                    r'<a:bodyPr lIns="91440" tIns="45720" rIns="91440" bIns="45720"\1\2>', sp, count=1)
        if not re.search(r"<a:(noAutofit|normAutofit|spAutoFit)", sp):
            sp = re.sub(r"<a:bodyPr([^>]*)/>", r"<a:bodyPr\1><a:noAutofit/></a:bodyPr>", sp, count=1)
            sp = re.sub(r"<a:bodyPr([^>]*)></a:bodyPr>", r"<a:bodyPr\1><a:noAutofit/></a:bodyPr>", sp, count=1)
        sp = re.sub(r"<a:pPr((?:[^>/]|/(?!>))*)/>", r'<a:pPr\1><a:lnSpc><a:spcPct val="100000"/></a:lnSpc></a:pPr>', sp)
        sp = re.sub(r"<a:pPr((?:[^>/]|/(?!>))*)>(?!<a:lnSpc>)", r'<a:pPr\1><a:lnSpc><a:spcPct val="100000"/></a:lnSpc>', sp)
        return sp

    return _SP.sub(fix, xml)
