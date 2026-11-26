"""XML 转义、单位换算、颜色工具。"""
import re

EMU = 914400  # 1 英寸
PT = 12700  # 1 磅

_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def esc(s):
    """XML 文本/属性转义（顺带去掉 XML 1.0 非法控制字符）"""
    s = _XML_BAD.sub("", str(s))
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def emu(inches):
    v = float(inches or 0)
    if v != v or v in (float("inf"), float("-inf")):  # NaN/Inf 写进 XML 会让 PowerPoint 判定损坏
        v = 0.0
    return int(round(v * EMU))


def pts(points):
    """磅 → EMU"""
    try:
        return int(round(float(points) * PT))
    except (TypeError, ValueError):
        return 0


_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")


def hexcolor(c, default="000000"):
    if not c:
        return default
    m = _HEX.match(str(c).strip())
    return m.group(1).upper() if m else default


def color_xml(color, transparency=0, alpha=None):
    """<a:srgbClr>；transparency 0-100（pptxgenjs 口径），alpha 0-1 直接给不透明度"""
    c = hexcolor(color)
    a = None
    if alpha is not None:
        a = max(0, min(100000, int(round(alpha * 100000))))
    elif transparency:
        a = max(0, min(100000, int(round((100 - float(transparency)) * 1000))))
    if a is None or a >= 100000:
        return '<a:srgbClr val="%s"/>' % c
    return '<a:srgbClr val="%s"><a:alpha val="%d"/></a:srgbClr>' % (c, a)


def solid_fill(color, transparency=0, alpha=None):
    return "<a:solidFill>%s</a:solidFill>" % color_xml(color, transparency, alpha)


def mix(a, b, t):
    """两色线性混合（t=0 → a，t=1 → b），返回大写 hex"""
    a = hexcolor(a)
    b = hexcolor(b)
    out = []
    for i in (0, 2, 4):
        va = int(a[i:i + 2], 16)
        vb = int(b[i:i + 2], 16)
        out.append("%02X" % int(_round_half_up(va + (vb - va) * t)))
    return "".join(out)


def _round_half_up(x):
    # 与 JS Math.round 一致（.5 向正无穷）
    import math
    return math.floor(x + 0.5)


js_round = _round_half_up


def fnum(v):
    """数字 → 紧凑字符串（XML 属性用）"""
    if isinstance(v, int):
        return str(v)
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"
