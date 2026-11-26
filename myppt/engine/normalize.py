"""AI / 人工写的页面 JSON「宽进」规范化（移植 contracts/page-normalize.ts）。

弱模型最常见的不是内容错，而是形状错：items 写成字符串数组、数字写成字符串、
字段名用了同义词（title/heading、desc/text）、单个对象没包数组……
这里先按契约把能确定意图的形状改对，改不了的留给校验报错，不猜内容。
"""
import math
import re

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _is_obj(v):
    return isinstance(v, dict)


def _num_str(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return str(v)
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    return str(v)


def to_str(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return _num_str(v)
    if _is_obj(v):
        for k in ("text", "title", "name", "content"):
            if v.get(k) is not None:
                return to_str(v.get(k)) if not _is_obj(v.get(k)) else ""
        return ""
    return ""


def _arr(v):
    if v is None:
        return None
    return v if isinstance(v, list) else [v]


def _pick(o, *keys):
    for k in keys:
        v = o.get(k)
        if v is not None and v != "":
            return v
    return None


def to_num(v):
    """"87%" "1,234.5" "约12" → float；不是数字返回 None"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v if (isinstance(v, int) or math.isfinite(v)) else None
    m = _NUM.search(to_str(v) if v is not None else "")
    if not m:
        return None
    try:
        n = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    if not math.isfinite(n):
        return None
    return int(n) if n.is_integer() else n


def _str_list(v):
    a = _arr(v)
    if a is None:
        return None
    return [s for s in (to_str(x) for x in a) if s.strip() != ""]


def _chart(c):
    if not _is_obj(c):
        return c
    o = dict(c)
    o["categories"] = [to_str(x) for x in (_arr(_pick(o, "categories", "labels", "xAxis", "x")) or [])]
    series = _arr(_pick(o, "series", "data", "datasets"))
    if series and all(isinstance(x, (int, float, str)) and not isinstance(x, bool) for x in series):
        series = [{"name": to_str(o.get("title")) or "数值", "values": series}]
    out = []
    for s in series or []:
        if not _is_obj(s):
            out.append(s)
            continue
        vals = _arr(_pick(s, "values", "data", "value")) or []
        ns = dict(s)
        ns["name"] = to_str(_pick(s, "name", "label")) or "数值"
        ns["values"] = [(to_num(x) if to_num(x) is not None else 0) for x in vals]
        out.append(ns)
    o["series"] = out
    for k in ("labels", "data", "datasets"):
        o.pop(k, None)
    if o.get("highlight") is not None:
        h = to_num(o["highlight"])
        if h is None:
            o.pop("highlight")
        else:
            o["highlight"] = max(0, int(math.floor(h + 0.5)))
    if o.get("unit") is not None:
        o["unit"] = to_str(o["unit"])
    return o


def normalize_page(inp):
    """规范化单页；不认识的字段原样保留"""
    if not _is_obj(inp):
        return inp
    p = dict(inp)
    if p.get("title") is not None:
        p["title"] = to_str(p["title"])
    if p.get("items") is not None:
        items = []
        for it in _arr(p["items"]):
            if _is_obj(it):
                d = dict(it)
                d["text"] = to_str(_pick(it, "text", "content", "title", "desc"))
            else:
                d = {"text": to_str(it)}
            if d["text"].strip():
                items.append(d)
        p["items"] = items
    if p.get("groups") is not None:
        p["groups"] = [dict(g, heading=to_str(_pick(g, "heading", "title", "name")), items=_str_list(g.get("items")) or [])
                       for g in _arr(p["groups"]) if _is_obj(g)]
    if p.get("stats") is not None:
        p["stats"] = [dict(s, value=to_str(_pick(s, "value", "number", "num")), label=to_str(_pick(s, "label", "name", "desc", "title")))
                      if _is_obj(s) else {"value": to_str(s), "label": ""} for s in _arr(p["stats"])]
    if p.get("takeaways") is not None:
        p["takeaways"] = _str_list(p["takeaways"])
    for side in ("left", "right"):
        s = p.get(side)
        if _is_obj(s):
            p[side] = dict(s, name=to_str(_pick(s, "name", "title", "heading")), points=_str_list(_pick(s, "points", "items")) or [])
    if p.get("headers") is not None:
        p["headers"] = [to_str(x) for x in _arr(p["headers"])]
    if p.get("rows") is not None:
        rows = []
        for r in _arr(p["rows"]):
            if isinstance(r, list):
                rows.append([to_str(c) for c in r])
            elif _is_obj(r):
                rows.append([to_str(c) for c in r.values()])
            else:
                rows.append([to_str(r)])
        p["rows"] = rows
    if p.get("steps") is not None:
        steps = []
        for s in _arr(p["steps"]):
            if _is_obj(s):
                d = dict(s)
                d["title"] = to_str(_pick(s, "title", "name", "heading", "step"))
                desc = _pick(s, "desc", "description", "text", "content")
                if desc is not None:
                    d["desc"] = to_str(desc)
                steps.append(d)
            else:
                steps.append({"title": to_str(s)})
        p["steps"] = steps
    if p.get("timeline") is not None:
        tl = []
        for t in _arr(p["timeline"]):
            if _is_obj(t):
                d = dict(t)
                d["label"] = to_str(_pick(t, "label", "time", "date", "year"))
                d["title"] = to_str(_pick(t, "title", "name", "event"))
                desc = _pick(t, "desc", "description", "text")
                if desc is not None:
                    d["desc"] = to_str(desc)
                tl.append(d)
            else:
                tl.append({"label": "", "title": to_str(t)})
        p["timeline"] = tl
    if p.get("cols") is not None:
        cols = []
        for c in _arr(p["cols"]):
            if not _is_obj(c):
                continue
            d = dict(c)
            d["heading"] = to_str(_pick(c, "heading", "title", "name"))
            d["text"] = to_str(_pick(c, "text", "desc", "content", "description"))
            if c.get("value") is not None:
                d["value"] = to_str(c["value"])
            if c.get("icon") is not None:
                d["icon"] = to_str(c["icon"])
            cols.append(d)
        p["cols"] = cols
    if p.get("iconItems") is not None:
        p["iconItems"] = [dict(c, icon=to_str(c.get("icon")) or "chart", heading=to_str(_pick(c, "heading", "title", "name")),
                               desc=to_str(_pick(c, "desc", "text", "content", "description")))
                          for c in _arr(p["iconItems"]) if _is_obj(c)]
    if p.get("quadrants") is not None:
        p["quadrants"] = [dict(q, name=to_str(_pick(q, "name", "title", "heading")), items=_str_list(q.get("items")) or [])
                          for q in _arr(p["quadrants"]) if _is_obj(q)]
    if p.get("layers") is not None:
        p["layers"] = [dict(l, name=to_str(_pick(l, "name", "title"))) if _is_obj(l) else {"name": to_str(l)} for l in _arr(p["layers"])]
    if p.get("gauges") is not None:
        gs = []
        for g in _arr(p["gauges"]):
            if not _is_obj(g):
                continue
            v = to_num(_pick(g, "value", "percent", "rate"))
            d = dict(g)
            d["label"] = to_str(_pick(g, "label", "name", "title"))
            d["value"] = v if v is not None else 0
            if g.get("display") is not None:
                d["display"] = to_str(g["display"])
            elif isinstance(g.get("value"), str) and "%" in g["value"]:
                d["display"] = g["value"]
            if g.get("target") is not None:
                d["target"] = to_str(g["target"])
            gs.append(d)
        p["gauges"] = gs
    if p.get("chart") is not None:
        p["chart"] = _chart(p["chart"])
    if p.get("quote") is not None and not isinstance(p["quote"], str):
        p["quote"] = to_str(p["quote"])
    if "note" in p and p["note"] is None:
        p.pop("note")
    return p


def normalize_pages(pages):
    return [normalize_page(p) for p in pages] if isinstance(pages, list) else []
