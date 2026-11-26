"""设计语言：同一套积木，换一套「手法」画出来，让每套模板在版式上真正不同，而不只是换色。

每种设计语言规定（全部是程序参数，模型只选是哪一种）：
  · 卡片怎么画：浅色块 / 圆角白卡浮起 / 只有细线 / 实色大色块 / 金色细框 / 科技角标
  · 图标怎么画：实心圆 / 圆角方块 / 只画线条 / 方块 / 细圆环
  · 要点符号、结论条样式、留白宽窄、页面底色、标题对齐
  · 构图偏好：同一页内容，不同语言优先挑不同的搭法（如杂志风偏爱细线列表，色块风偏爱卡片网格）
"""
LANGS = {
    "corporate": dict(watermark=True, emph=True, name="商务稳重", cards={}, icon="solid", marker=None, callout="bar", bg=None, area=None,
                      kpi="primary", align="left", toc="tiles",
                      prefer=("chart-panel", "table-bars", "flow", "kpi-panel", "cards-top", "kpi-topbar", "grid", "grid3", "chart-side", "soft-accent", "rows")),
    "rounded": dict(watermark=True, emph=True, name="圆润亲和", cards={"soft": "raised", "topbar": "raised", "outline": "raised", "leftbar": "raised"},
                    icon="tile", marker="ring", callout="pill", bg="tint", area=None, kpi="primary", align="left",
                    toc="cards",
                    prefer=("orbs", "hub", "versus", "flow", "cards-top", "cards", "kpi-cards", "grid2-soft", "num-grid", "tl-cards", "faq-grid",
                            "soft-accent", "matrix-cards", "rings", "bands")),
    "editorial": dict(watermark=False, emph=False, name="杂志留白", cards={"soft": "rule", "topbar": "rule", "outline": "rule", "leftbar": "rule",
                                         "accent": "rule", "dark": "rule", "panel": "panel-light"},
                      icon="glyph", marker="dash", callout="quote", bg=None, area=dict(x=160, w=1600), kpi="ink",
                      align="left", toc="numbers",
                      prefer=("tl-line", "table-bars", "panel-claim", "list", "head-rows", "plain-top", "two-col", "side-claim", "matrix-lines", "faq-list",
                              "bars", "tl-rows", "rows", "kpi-plain", "outline", "chart-callout", "table", "num-rows")),
    "bold": dict(watermark=True, emph=False, name="大色块", cards={"soft": "block", "topbar": "block", "outline": "block", "leftbar": "block"},
                 icon="glyph", marker="square", callout="dark", bg=None, area=None, kpi="primary", align="left",
                 toc="blocks",
                 prefer=("panel-claim", "kpi-panel", "versus", "quote-panel", "flow", "lead-first", "cards", "kpi-hero", "kpi-cards", "grid3", "matrix-cards", "tl-cards",
                         "faq-grid", "soft-accent", "cards-top")),
    "luxury": dict(watermark=False, emph=False, name="典雅细框", cards={"soft": "fine", "topbar": "fine", "outline": "fine", "leftbar": "fine",
                                       "accent": "fine", "dark": "fine", "panel": "panel-light"},
                   icon="ring", marker="diamond", callout="fine", bg="frame", area=dict(x=200, w=1520), kpi="accent",
                   align="center", toc="center",
                   prefer=("orbs", "tl-line", "quote-panel", "versus", "plain-top", "quote-center", "rings", "kpi-plain", "list", "outline", "matrix-lines",
                           "tl-rows", "faq-list", "chart-callout", "two-col")),
    "tech": dict(watermark=True, emph=True, name="科技网格", cards={"soft": "bracket", "topbar": "bracket", "outline": "bracket", "leftbar": "bracket"},
                 icon="square", marker="square", callout="code", bg="grid", area=None, kpi="primary", align="left",
                 toc="cards",
                 prefer=("hub", "flow", "table-bars", "tl-line", "num-grid", "grid2-soft", "num-rows", "kpi-grid", "faq-grid", "tl-grid", "matrix-cards",
                         "rings", "kpi-rings", "chart-side", "table-side", "bands")),
}
COVER_LANG = {"diagonal": "corporate", "split": "rounded", "arcs": "editorial", "band": "bold", "frame": "luxury",
              "mosaic": "tech"}

# 当前设计语言（出稿开始时设置；渲染是同步的）
CUR = dict(LANGS["corporate"], id="corporate")


def use(lang_id):
    lid = lang_id if lang_id in LANGS else "corporate"
    CUR.clear()
    CUR.update(LANGS[lid])
    CUR["id"] = lid


def remap(n):
    """把积木里的通用卡片样式换成当前设计语言的样式（原地修改，返回同一棵树）"""
    m = CUR.get("cards") or {}
    st = n.get("style", "none")
    if st in m:
        n["style"] = m[st]
    if n.get("el") == "bullets" and CUR.get("marker") and n.get("marker", "dot") == "dot":
        n["marker"] = CUR["marker"]
    if n.get("el") == "heading" and CUR.get("align") == "center" and "align" not in n:
        n["align"] = "center"
    if n.get("el") == "kpi" and "align" not in n and CUR.get("align") == "center":
        n["align"] = "center"
    for c in n.get("children") or []:
        remap(c)
    return n


def emphasize(n):
    """主次：一排 ≥3 张同样式的指标卡，第一张（通常是头号指标）换成主色实底，其余保持浅色"""
    if not CUR.get("emph") or "el" in n:
        return n
    kids = n.get("children") or []
    if n.get("box") == "row" and len(kids) >= 3:
        sts = set(k.get("style", "none") for k in kids)
        if len(sts) == 1 and list(sts)[0] in ("soft", "raised", "bracket", "outline", "topbar") and all(
                _has(k, "kpi") for k in kids):
            kids[0]["style"] = "accent"
            for c in _leaves(kids[0]):
                if c.get("color") in ("ink", "primary"):
                    c.pop("color")
            return n
    for c in kids:
        emphasize(c)
    return n


def _leaves(n):
    if "el" in n:
        return [n]
    out = []
    for c in n.get("children") or []:
        out += _leaves(c)
    return out


def _has(n, el):
    return any(c.get("el") == el for c in _leaves(n))


def bonus(candidate_name):
    return 22 if candidate_name in (CUR.get("prefer") or ()) else 0
