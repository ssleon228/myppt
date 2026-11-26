"""deck.json 校验：按 deck.schema.json（与 TS 版 zod 契约一致）逐页检查结构。

只拦截结构错误（缺字段、类型不对、未知页型），不管字数——超字数由排版自动缩字处理。
自带一个够用的 JSON Schema 子集校验器（type/properties/required/items/prefixItems/enum/const/
anyOf/oneOf/maxLength/minimum/maximum），不依赖 jsonschema 库。
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA = None

TYPE_CN = {"string": "字符串", "number": "数字", "integer": "整数", "boolean": "布尔值", "object": "对象", "array": "数组", "null": "null"}


def deck_schema():
    global _SCHEMA
    if _SCHEMA is None:
        with open(os.path.join(_HERE, "deck.schema.json"), encoding="utf-8") as f:
            _SCHEMA = json.load(f)
    return _SCHEMA


def page_schema():
    return deck_schema()["properties"]["pages"]["items"]


def _type_of(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _type_ok(v, t):
    actual = _type_of(v)
    if t == "number":
        return actual in ("number", "integer")
    if t == "integer":
        return actual == "integer" or (actual == "number" and float(v).is_integer())
    return actual == t


def validate(value, schema, path=()):
    """返回 [(path_tuple, message)]"""
    errs = []
    if not isinstance(schema, dict) or not schema:
        return errs
    if "anyOf" in schema or "oneOf" in schema:
        branches = schema.get("anyOf") or schema.get("oneOf")
        # 判别联合：分支都有 kind/type 常量时按常量挑分支，报错更准
        disc = _discriminator(branches)
        if disc and isinstance(value, dict):
            want = value.get(disc)
            for b in branches:
                if b.get("properties", {}).get(disc, {}).get("const") == want:
                    return validate(value, b, path)
            opts = [b["properties"][disc]["const"] for b in branches]
            return [(path + (disc,), "取值必须是以下之一：%s" % "、".join(map(str, opts)))]
        best = None
        for b in branches:
            e = validate(value, b, path)
            if not e:
                return []
            if best is None or len(e) < len(best):
                best = e
        return best or []
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, x) for x in types):
            return [(path, "应为%s，实际是%s" % ("或".join(TYPE_CN.get(x, x) for x in types), TYPE_CN.get(_type_of(value), _type_of(value))))]
    if "const" in schema and value != schema["const"]:
        errs.append((path, "必须是 %s" % json.dumps(schema["const"], ensure_ascii=False)))
    if "enum" in schema and value not in schema["enum"]:
        errs.append((path, "取值必须是以下之一：%s（当前：%s）" % ("、".join(map(str, schema["enum"])), value)))
    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        errs.append((path, "长度不能超过 %d（当前 %d）" % (schema["maxLength"], len(value))))
    if _type_of(value) in ("number", "integer"):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append((path, "不能小于 %s" % schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errs.append((path, "不能大于 %s" % schema["maximum"]))
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value or value[k] is None:
                errs.append((path + (k,), "缺少必填字段"))
        for k, sub in schema.get("properties", {}).items():
            if k in value and value[k] is not None:
                errs += validate(value[k], sub, path + (k,))
            elif k in value and value[k] is None and k not in schema.get("required", []):
                # zod optional 不接受 null：与 TS 版一致报错
                errs.append((path + (k,), "不能为 null（可省略该字段）"))
    if isinstance(value, list):
        pre = schema.get("prefixItems")
        if pre:
            if len(value) != len(pre):
                errs.append((path, "应为 %d 个元素" % len(pre)))
            for i, sub in enumerate(pre[:len(value)]):
                errs += validate(value[i], sub, path + (i,))
        elif "items" in schema:
            for i, v in enumerate(value):
                errs += validate(v, schema["items"], path + (i,))
    return errs


def _discriminator(branches):
    for key in ("kind", "type"):
        if branches and all(isinstance(b, dict) and "const" in b.get("properties", {}).get(key, {}) for b in branches):
            return key
    return None


def validate_pages(pages):
    """→ [{'path': '第3页（chart） chart.series.0.values', 'message': ...}]"""
    out = []
    ps = page_schema()
    for i, p in enumerate(pages):
        for path, msg in validate(p, ps, ()):
            typ = p.get("type", "?") if isinstance(p, dict) else "?"
            where = "第%d页（%s）" % (i + 1, typ)
            rest = ".".join(str(x) for x in path)
            out.append({"path": (where + " " + rest).strip(), "message": msg, "page": i + 1})
    return out
