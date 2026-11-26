"""文字适配：写入文本框前按真实字宽估算折行后的高度，放不下就整体等比缩小字号（只缩不放）。

旧版只对少数位置（大数字、章节标题、design 页）做了缩字，结构化页型里 AI 写长了就会溢出卡片。
这里在 Slide.add_text 统一兜底：所有页型、所有变体都不会再冲出文本框。

口径（与 PowerPoint 接近、略保守）：
  · 单倍行距 = 1.2 × 字号；lineSpacingMultiple 按倍数放大；lineSpacing（磅）按固定值；
  · 文本框默认内边距 左右 0.1in、上下 0.05in；margin 按磅；
  · 中文逐字折行，西文按单词折行（单词太长再逐字）。
"""
import re

from . import fontmetrics

LINE = 1.2
MIN_SCALE = 0.55
MIN_PT = 9.0
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9.,%+\-_/']*|\s+|.", re.S)


def _insets(o):
    m = o.get("margin")
    if m is None:
        return 0.1 * 72, 0.1 * 72, 0.05 * 72, 0.05 * 72  # l r b t（磅）
    if isinstance(m, (list, tuple)):
        l, r, b, t = (list(m) + [0, 0, 0, 0])[:4]
        return float(l or 0), float(r or 0), float(b or 0), float(t or 0)
    return float(m), float(m), float(m), float(m)


def _paragraphs(runs, o):
    paras = [[]]
    for i, r in enumerate(runs):
        eff = dict(o)
        for k, v in (r.get("options") or {}).items():
            if v or k not in eff:
                eff[k] = v
        paras[-1].append((r.get("text") or "", eff))
        if (r.get("options") or {}).get("breakLine") and i + 1 < len(runs):
            paras.append([])
    return paras


def _measure(paras, width_pt, scale, font, latin, wrap=True):
    """→ (总高度 磅, 最长行宽 磅, 总行数)"""
    total = 0.0
    nlines = 0
    widest = 0.0
    for p in paras:
        size_max = 0.0
        lines = 1
        cur = 0.0
        ls_mult = None
        ls_pts = None
        before = after = 0.0
        for text, eff in p:
            sz = float(eff.get("fontSize") or 18) * scale
            size_max = max(size_max, sz if text.strip() or not size_max else 0)
            f = eff.get("fontFace") or font
            ls_mult = eff.get("lineSpacingMultiple") or ls_mult
            ls_pts = eff.get("lineSpacing") or ls_pts
            before = max(before, float(eff.get("paraSpaceBefore") or 0))
            after = max(after, float(eff.get("paraSpaceAfter") or 0))
            sp = float(eff.get("charSpacing") or 0)
            for tok in _WORD.findall(text):
                w = sum(fontmetrics.char_em(ch, f, latin) * sz + sp for ch in tok)
                if not wrap:
                    cur += w
                    continue
                if tok.isspace():
                    cur += w
                    continue
                if cur + w <= width_pt:
                    cur += w
                    continue
                if len(tok) > 1 and w > width_pt:  # 超长单词：逐字
                    for ch in tok:
                        cw = fontmetrics.char_em(ch, f, latin) * sz + sp
                        if cur + cw > width_pt and cur > 0:
                            widest = max(widest, cur)
                            lines += 1
                            cur = 0.0
                        cur += cw
                    continue
                if cur > 0:
                    widest = max(widest, cur)
                    lines += 1
                    cur = w
                else:
                    cur = w
        widest = max(widest, cur)
        if size_max <= 0:
            size_max = float((p[0][1].get("fontSize") if p else None) or 18) * scale
        lh = float(ls_pts) if ls_pts else size_max * LINE * float(ls_mult or 1)
        total += lines * lh + before + after
        nlines += lines
    return total, widest, nlines


def fit_scale(runs, o, font, latin=None):
    """返回字号缩放系数（≤1）；1 表示放得下"""
    w_in, h_in = o.get("w"), o.get("h")
    if not w_in or not h_in or o.get("fit") == "shrink":
        return 1.0
    l, r, b, t = _insets(o)
    width = float(w_in) * 72 - l - r
    height = float(h_in) * 72 - t - b
    if width <= 4 or height <= 4:
        return 1.0
    wrap = o.get("wrap", True) is not False
    paras = _paragraphs(runs, o)
    if not any(txt.strip() for p in paras for txt, _ in p):
        return 1.0
    need_h, widest, nl = _measure(paras, width, 1.0, font, latin, wrap)
    # 只有一行的文字框不按高度缩：设计稿里单行标签常常故意贴着字高放（居中时上下对称溢出，不影响观感）
    over_h = nl > 1 and need_h > height * 1.04
    over_w = (not wrap) and widest > width * 1.02
    if not over_h and not over_w:
        return 1.0
    max_pt = max(float(eff.get("fontSize") or 18) for p in paras for _, eff in p)
    lo = max(MIN_SCALE, MIN_PT / max_pt) if max_pt > 0 else MIN_SCALE
    if lo >= 1:
        return 1.0
    # 二分找最大可行缩放
    good, bad = lo, 1.0
    for _ in range(12):
        mid = (good + bad) / 2
        h2, w2, n2 = _measure(paras, width, mid, font, latin, wrap)
        ok = (n2 <= 1 or h2 <= height * 1.04) and (wrap or w2 <= width * 1.02)
        if ok:
            good = mid
        else:
            bad = mid
    return good
