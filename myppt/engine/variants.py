"""版式变体 + 整套节奏（移植 contracts/layout-variants.ts，纯函数、确定性）。

每个高频页型有 2-5 个视觉变体；变体只改「怎么摆」，不改页的数据字段。
选择顺序：page.variant 显式指定 > 按内容量自动选 > 节奏规则微调。
节奏规则：每 3-4 页至少一页「强视觉页」，同页型相邻两页不用同一变体。
"""
import re

PAGE_VARIANTS = {
    "bullets": ["default", "numbered", "split", "groupcols"],
    "columns": ["default", "lined", "metric"],
    "table": ["default", "clean", "heat"],
    "kpi": ["default", "scorecard"],
    "imagetext": ["default", "halfbleed"],
    "combo": ["default", "comboHero"],
    "stats": ["default", "hero", "row", "band", "dashboard"],
    "quote": ["default", "statement"],
    "image": ["default", "fullbleed"],
    "chart": ["default", "annotated", "ranking"],
    "compare": ["default", "beforeafter", "versus"],
    "timeline": ["default", "roadmap"],
    "steps": ["default", "roadmap", "chevron", "grid"],
    "chapter": ["default", "bold"],
}

STRONG_VARIANTS = {"split", "band", "statement", "fullbleed", "bold"}
HEADERLESS_VARIANTS = {"split", "band", "statement", "fullbleed", "bold"}

VARIANT_LABELS = {
    "default": "标准", "numbered": "大序号两栏", "split": "左深色面板", "hero": "超大数字", "row": "数字横排",
    "band": "深色数字带", "statement": "深色金句", "fullbleed": "整版图片", "annotated": "带注释图表",
    "beforeafter": "现状→目标", "roadmap": "路线图", "bold": "深色大序号", "chevron": "箭头流程", "lined": "无卡片多栏",
    "groupcols": "分组分栏", "clean": "报表风表格", "halfbleed": "半边大图", "comboHero": "数字栈+图表", "versus": "双栏 VS",
    "scorecard": "指标记分卡", "ranking": "排名横条", "metric": "数字领衔卡", "heat": "达标分色报表", "grid": "举措网格",
    "dashboard": "经营总览",
}

BEFORE_AFTER_RE = re.compile(r"现状|当前|目前|过去|以前|之前|传统|旧|改造前|before|as.?is", re.I)
AFTER_RE = re.compile(r"目标|未来|之后|升级|新|改造后|after|to.?be", re.I)


def _is_valid(t, v):
    return bool(v) and v in PAGE_VARIANTS.get(t, [])


def _items(page):
    return page.get("items") or []


def _txt(i):
    if isinstance(i, dict):
        return i.get("text") or ""
    return i if isinstance(i, str) else ""


def candidates(page):
    t = page.get("type")
    if t == "bullets":
        groups = page.get("groups") or []
        if groups:
            return ["groupcols", "default"] if len(groups) <= 4 else ["default"]
        items = _items(page)
        n = len(items)
        long_ = any(len(_txt(i)) > 46 for i in items)
        if n >= 3:
            return ["default", "numbered"] if long_ else ["numbered", "default"]
        return ["default"]
    if t == "stats":
        n = len(page.get("stats") or [])
        if n <= 2:
            return ["hero", "default"]
        if n >= 4:
            return ["dashboard", "row", "band", "default"]
        return ["row", "dashboard", "band", "default"]
    if t == "quote":
        return ["statement", "default"]
    if t == "image":
        return ["default"] if len(page.get("caption") or "") > 60 else ["fullbleed", "default"]
    if t == "chart":
        c = page.get("chart")
        if not c:
            return ["default"]
        series = c.get("series") or []
        cats = c.get("categories") or []
        single = len(series) == 1
        kind = c.get("kind")
        if single and kind in ("bar", "barH") and 9 <= len(cats) <= 16:
            return ["ranking", "default"]
        if single and kind == "barH" and 3 <= len(cats) <= 16:
            return ["ranking", "default"]
        simple = kind in ("bar", "line") and single and 3 <= len(cats) <= 8
        if simple:
            return ["annotated", "ranking", "default"] if (kind == "bar" and len(cats) >= 6) else ["annotated", "default"]
        return ["default"]
    if t == "compare":
        l = (page.get("left") or {}).get("name", "") + ((page.get("left") or {}).get("nameEn") or "")
        r = (page.get("right") or {}).get("name", "") + ((page.get("right") or {}).get("nameEn") or "")
        return ["beforeafter", "versus"] if (BEFORE_AFTER_RE.search(l) or AFTER_RE.search(r)) else ["versus", "default"]
    if t == "timeline":
        n = len(page.get("timeline") or [])
        return ["roadmap", "default"] if 3 <= n <= 6 else ["default"]
    if t == "steps":
        steps = page.get("steps") or []
        n = len(steps)
        long_ = any(len(s.get("desc") or "") > 34 for s in steps)
        if 3 <= n <= 6 and long_:
            return ["grid", "chevron", "default"]
        return ["chevron", "grid", "roadmap", "default"] if 3 <= n <= 6 else ["default"]
    if t == "columns":
        cols = page.get("cols") or []
        n = len(cols)
        has_img = any(c.get("image") for c in cols)
        if not has_img and 2 <= n <= 4 and all((c.get("value") or "").strip() for c in cols):
            return ["metric", "lined", "default"]
        return ["lined", "default"] if (not has_img and 2 <= n <= 4) else ["default"]
    if t == "table":
        headers = page.get("headers") or []
        rows = page.get("rows") or []
        nc = len(headers)
        rated = any(re.search(r"率|进度|完成", h) for h in headers) or any(
            re.search(r"\d%$", str(c if c is not None else "").strip()) for r in rows for c in r)
        if 2 <= nc <= 7 and len(rows) <= 12 and rated:
            return ["heat", "clean", "default"]
        return ["clean", "default"] if (2 <= nc <= 6 and len(rows) <= 9) else ["default"]
    if t == "imagetext":
        return ["halfbleed", "default"] if (page.get("image") and page.get("direction") != "top") else ["default"]
    if t == "kpi":
        gs = page.get("gauges") or []
        return ["scorecard", "default"] if (len(gs) >= 3 or any((g.get("value") or 0) > 100 for g in gs)) else ["default", "scorecard"]
    if t == "combo":
        return ["comboHero", "default"] if (page.get("chart") and page.get("stats")) else ["default"]
    return ["default"]


def strong_alternative(page):
    t = page.get("type")
    if t == "stats" and 2 <= len(page.get("stats") or []) <= 4:
        return "band"
    if t == "bullets" and not page.get("groups"):
        items = _items(page)
        if 3 <= len(items) <= 4 and all(len(_txt(i)) <= 46 for i in items):
            return "split"
    return None


def _is_frame(p):
    return p.get("type") in ("cover", "chapter", "end")


def resolve_variants(pages):
    out = []
    explicit = []
    for i, p in enumerate(pages):
        if _is_valid(p.get("type"), p.get("variant")):
            out.append(p["variant"])
            explicit.append(True)
            continue
        explicit.append(False)
        if _is_frame(p):
            out.append("bold" if p.get("type") == "chapter" else "default")
            continue
        cands = candidates(p)
        v = cands[0]
        if i > 0 and pages[i - 1].get("type") == p.get("type") and out[i - 1] == v and len(cands) > 1:
            v = cands[1]
        out.append(v)

    def strong(i):
        return 0 <= i < len(pages) and (_is_frame(pages[i]) or out[i] in STRONG_VARIANTS)

    def natural(i):
        return pages[i].get("type") in ("quote", "image")

    for i in range(1, len(pages)):
        a = i - 1
        if _is_frame(pages[a]) or _is_frame(pages[i]):
            continue
        if out[a] not in STRONG_VARIANTS or out[i] not in STRONG_VARIANTS:
            continue
        if natural(a) and not natural(i):
            order = [i, a]
        elif natural(i) and not natural(a):
            order = [a, i]
        else:
            order = [i, a]
        for j in order:
            if explicit[j]:
                continue
            calm = next((c for c in candidates(pages[j]) if c not in STRONG_VARIANTS), None)
            if calm:
                out[j] = calm
                break
    since = 0
    for i in range(len(pages)):
        if strong(i):
            since = 0
            continue
        since += 1
        if since >= 3 and not explicit[i] and not strong(i + 1) and not strong(i - 1):
            alt = strong_alternative(pages[i])
            if alt:
                out[i] = alt
                since = 0
    return out
