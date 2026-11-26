"""积木结构（版面描述）的校验与自动修正。

AI 写的版面只能用这些东西：
  容器 {"box": "row"|"col"|"grid", "children": [...], "gap": "s|m|l", "w": 1-12, "style": 卡片样式, "pad": "s|m|l",
        "align": "start|center|spread", "cols": grid 每行几个}
  元素 {"el": 元素名, ...元素字段, "w": 1-12, "style": 卡片样式}
不认识的字段丢掉、档位写错改回默认、超出上限的拆开或截断，全部记成「修正」告诉调用方；
修不了的（没有内容、元素名不认识）记成「问题」。程序不猜内容。
"""
from .blocks import LEAVES
from .tokens import GAP, PAD, STYLES, COLOR_ROLES

MAX_DEPTH = 4
MAX_ROW = 4
MAX_COL = 7
MAX_LEAVES = 14

REQUIRED = {"heading": "text", "text": "text", "kpi": "value", "quote": "text", "callout": "text", "chart": "chart",
            "image": "src", "bullets": "items", "table": "rows",
            "progress": "value", "ring": "value",
            "flow": "items", "timeline": "items", "hbars": "items", "hub": "items", "orbs": "items"}
ALIAS_EL = {"title": "heading", "h": "heading", "paragraph": "text", "p": "text", "list": "bullets", "ul": "bullets",
            "stat": "kpi", "metric": "kpi", "number": "kpi", "card": "iconitem", "feature": "iconitem",
            "icon": "iconitem", "conclusion": "callout", "takeaway": "callout", "img": "image", "picture": "image",
            "graph": "chart", "line": "divider", "hr": "divider",
            "bar": "progress", "gauge": "ring", "donut": "ring"}
LEAF_KEYS = {"el", "w", "style", "pad", "text", "role", "color", "align", "valign", "bold", "kicker", "sub", "items",
             "marker", "spread", "value", "label", "delta", "icon", "head", "layout", "n", "by", "chart", "headers",
             "rows", "highlight", "src", "fit", "display", "target", "good_at", "center"}


class Fix:
    def __init__(self):
        self.fixes = []
        self.errors = []

    def fix(self, path, msg):
        self.fixes.append("%s：%s" % (path, msg))

    def err(self, path, msg):
        self.errors.append("%s：%s" % (path, msg))


def _enum(node, key, allowed, default, f, path):
    v = node.get(key)
    if v is None:
        return default
    if v in allowed:
        return v
    f.fix(path, "%s=%r 不在可选档位 %s 里，改为 %r" % (key, v, "/".join(allowed), default))
    return default


def _weight(node, f, path):
    v = node.get("w")
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        f.fix(path, "w 不是数字，忽略")
        return None
    if not 0.5 <= v <= 12:
        f.fix(path, "w=%s 超出 1-12，已夹到范围内" % v)
        v = max(1, min(12, v))
    return v


def _leaf(node, f, path):
    el = node.get("el")
    el = ALIAS_EL.get(el, el)
    if el not in LEAVES:
        f.err(path, "不认识的元素 %r（可用：%s）" % (node.get("el"), "、".join(LEAVES)))
        return None
    out = {k: v for k, v in node.items() if k in LEAF_KEYS}
    dropped = sorted(set(node) - LEAF_KEYS)
    if dropped:
        f.fix(path, "丢掉不支持的字段 %s（坐标、字号、颜色值都由程序决定）" % "、".join(dropped))
    out["el"] = el
    need = REQUIRED.get(el)
    if need:
        v = out.get(need)
        if v is None or v == "" or v == []:
            f.err(path, "%s 缺少 %s" % (el, need))
            return None
    if el == "iconitem" and not (out.get("head") or out.get("text")):
        f.err(path, "iconitem 至少要有 head 或 text")
        return None
    if el == "step" and not (out.get("head") or out.get("text")):
        f.err(path, "step 至少要有 head 或 text")
        return None
    if "color" in out and out["color"] not in COLOR_ROLES:
        f.fix(path, "color 只能用角色名（%s），%r 已去掉" % ("/".join(COLOR_ROLES), out["color"]))
        out.pop("color")
    if el == "kpi" and len(str(out["value"])) > 12:
        f.fix(path, "kpi 数值太长（%s），大数字只放数字和单位" % out["value"])
    if el == "bullets":
        items = out["items"] if isinstance(out["items"], list) else [out["items"]]
        if len(items) > 8:
            f.fix(path, "要点 %d 条太多，只保留前 8 条" % len(items))
            items = items[:8]
        out["items"] = items
        out["marker"] = _enum(out, "marker", ("dot", "num", "check", "icon", "bar", "none"), "dot", f, path)
    if el == "table":
        rows = out.get("rows") or []
        if len(rows) > 10:
            f.fix(path, "表格 %d 行太多，只保留前 10 行" % len(rows))
            out["rows"] = rows[:10]
    w = _weight(node, f, path)
    if w is not None:
        out["w"] = w
    out["style"] = _enum(node, "style", STYLES, "none", f, path)
    out["pad"] = _enum(node, "pad", tuple(PAD), "m", f, path)
    return out


def _box(node, f, path, depth):
    if depth > MAX_DEPTH:
        f.err(path, "嵌套超过 %d 层" % MAX_DEPTH)
        return None
    kind = node.get("box") or ("row" if node.get("dir") == "row" else "col")
    if kind not in ("row", "col", "grid"):
        f.fix(path, "box=%r 改为 col" % kind)
        kind = "col"
    kids_in = node.get("children") or []
    if not isinstance(kids_in, list):
        kids_in = [kids_in]
    kids = []
    for i, c in enumerate(kids_in):
        r = normalize_node(c, f, "%s/%d" % (path, i + 1), depth + 1)
        if r is not None:
            kids.append(r)
    if not kids:
        return None
    out = {"box": kind, "children": kids}
    out["gap"] = _enum(node, "gap", tuple(GAP), "m", f, path)
    out["style"] = _enum(node, "style", tuple(STYLES), "none", f, path)
    out["pad"] = _enum(node, "pad", tuple(PAD), "m", f, path)
    out["align"] = _enum(node, "align", ("start", "center", "spread"), "start", f, path)
    w = _weight(node, f, path)
    if w is not None:
        out["w"] = w
    if node.get("seq") and kind == "row":
        out["seq"] = True  # 顺序关系：卡片之间画衔接箭头
    if kind == "grid":
        cols = node.get("cols")
        try:
            cols = int(cols)
        except (TypeError, ValueError):
            cols = 2 if len(kids) in (4,) else min(3, len(kids))
        cols = max(1, min(MAX_ROW, cols))
        return _grid_to_rows(out, cols)
    if kind == "row" and len(kids) > MAX_ROW:
        f.fix(path, "一行 %d 个太多，自动折成每行 %d 个的网格" % (len(kids), 3))
        return _grid_to_rows(out, 3 if len(kids) != 8 else 4)
    if kind == "col" and len(kids) > MAX_COL:
        f.fix(path, "一列 %d 个太多，只保留前 %d 个" % (len(kids), MAX_COL))
        out["children"] = kids[:MAX_COL]
    if len(kids) == 1 and out["style"] == "none" and "w" not in out:
        return kids[0]  # 只有一个孩子的无样式容器：去掉这一层
    return out


def _grid_to_rows(g, cols):
    kids = g["children"]
    rows = []
    for i in range(0, len(kids), cols):
        part = kids[i:i + cols]
        # 最后一行不满：两行以上时让它自己等分（3+2 排法），只有一行时补空位保持宽度一致
        if len(part) < cols and len(kids) <= cols:
            while len(part) < cols:
                part.append({"el": "spacer", "style": "none", "pad": "m"})
        rows.append({"box": "row", "children": part, "gap": g["gap"], "style": "none", "pad": "m", "align": "start"})
    out = {"box": "col", "children": rows, "gap": g["gap"], "style": g["style"], "pad": g["pad"], "align": "spread",
           "_grid": True}
    if "w" in g:
        out["w"] = g["w"]
    return out


def normalize_node(node, f, path="layout", depth=1):
    if isinstance(node, list):
        node = {"box": "col", "children": node}
    if not isinstance(node, dict):
        f.err(path, "应为对象")
        return None
    if "el" in node:
        return _leaf(node, f, path)
    return _box(node, f, path, depth)


def count_leaves(n):
    if "el" in n:
        return 0 if n["el"] == "spacer" else 1
    return sum(count_leaves(c) for c in n["children"])


def normalize(layout):
    """→ (树 或 None, 修正列表, 问题列表)"""
    f = Fix()
    tree = normalize_node(layout, f)
    if tree is not None and count_leaves(tree) > MAX_LEAVES:
        f.err("layout", "元素 %d 个，超过一页上限 %d 个，内容请拆页" % (count_leaves(tree), MAX_LEAVES))
    if tree is not None and "el" in tree:
        tree = {"box": "col", "children": [tree], "gap": "m", "style": "none", "pad": "m", "align": "start"}
    return tree, f.fixes, f.errors


def signature(n):
    """结构指纹：判断相邻两页是不是「长得一样」"""
    if "el" in n:
        return n["el"] + ("" if n.get("style", "none") == "none" else "[" + n["style"] + "]")
    return "%s(%s)" % (n["box"], ",".join(signature(c) for c in n["children"]))


def family(n):
    """视觉家族：主要卡片样式 + 主要元素。连续几页同一家族会显得单调"""
    styles, els = {}, {}

    def walk(x):
        st = x.get("style", "none")
        if st != "none":
            styles[st] = styles.get(st, 0) + 1
        if "el" in x:
            if x["el"] not in ("spacer", "callout", "heading"):
                els[x["el"]] = els.get(x["el"], 0) + 1
        else:
            for c in x["children"]:
                walk(c)
    walk(n)
    st = max(styles, key=styles.get) if styles else "none"
    el = max(els, key=els.get) if els else "-"
    return st + "|" + el
