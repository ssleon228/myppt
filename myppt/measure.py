"""文字测量：复用 底层引擎 的真实字宽与折行口径（与导出 pptx 的 autofit 一致）。"""
from .engine import textfit, fontmetrics

FONT = {"cn": "微软雅黑", "latin": None}


def set_fonts(cn, latin):
    FONT["cn"] = cn
    FONT["latin"] = latin


def text_h(text, w, px, lh=1.3, bold=False):
    """文字在宽 w（px）内、字号 px 时的高度（px）"""
    if not str(text or "").strip():
        return 0.0
    width_pt = w / 2.0 * (0.95 if bold else 0.98)
    paras = [[(line, {"fontSize": px / 2.0, "lineSpacingMultiple": lh})] for line in str(text).split("\n")]
    h_pt, _, _ = textfit._measure(paras, width_pt, 1.0, FONT["cn"], FONT["latin"])
    return h_pt * 2.0


def lines(text, w, px, bold=False):
    width_pt = w / 2.0 * (0.95 if bold else 0.98)
    paras = [[(line, {"fontSize": px / 2.0})] for line in str(text or "").split("\n")]
    _, _, n = textfit._measure(paras, width_pt, 1.0, FONT["cn"], FONT["latin"])
    return n


def text_w(text, px, bold=False):
    """单行宽度（px）"""
    em = fontmetrics.text_em(str(text or ""), FONT["cn"], FONT["latin"])
    return em * px * (1.05 if bold else 1.0)


def widest(text, w, px, bold=False):
    """折行后最长一行的宽度（px）"""
    width_pt = w / 2.0 * (0.95 if bold else 0.98)
    paras = [[(line, {"fontSize": px / 2.0})] for line in str(text or "").split("\n")]
    _, wd, _ = textfit._measure(paras, width_pt, 1.0, FONT["cn"], FONT["latin"])
    return wd * 2.0
