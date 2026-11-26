"""主题：通用内置风格（默认第一套）+ 显式传入的模板目录（<id>/template.json）。
不读任何默认模板目录；实验版的整套模板由 pptlab.brand 画，用户模板由 pptlab.reuse 处理。
"""
import copy
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

def _default():
    with open(os.path.join(_HERE, "data", "builtin-themes.json"), encoding="utf-8") as f:
        return dict(json.load(f)[0], id="default")


DEFAULT_THEME = _default()

_ID_RE = re.compile(r"^[\w-]{1,64}$")


def builtin_themes():
    with open(os.path.join(_HERE, "data", "builtin-themes.json"), encoding="utf-8") as f:
        return json.load(f)


def template_dirs(extra=None):
    dirs = []
    if extra:
        dirs += [extra] if isinstance(extra, str) else list(extra)
    out = []
    for d in dirs:
        a = os.path.abspath(d)
        if a not in out and os.path.isdir(a):
            out.append(a)
    return out


def _read_template(d, tid):
    if not _ID_RE.match(tid):
        return None
    p = os.path.join(d, tid, "template.json")
    try:
        with open(p, encoding="utf-8") as f:
            t = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(t, dict) or not t.get("id") or not t.get("colors"):
        return None
    t["_dir"] = os.path.join(d, tid)
    return t


def stored_templates(extra=None):
    out = []
    seen = set()
    for d in template_dirs(extra):
        for name in sorted(os.listdir(d)):
            if name in seen:
                continue
            t = _read_template(d, name)
            if t:
                seen.add(name)
                out.append(t)
    out.sort(key=lambda t: t.get("createdAt") or "")
    return out


def source_name(t):
    """模板显示名：template.json 的 name；没有时取源 PPT 文件名（去掉 source- 前缀与扩展名）"""
    if isinstance(t, dict) and t.get("name"):
        return t["name"]
    src = template_source_pptx(t)
    if not src:
        return ""
    b = os.path.basename(src)
    b = re.sub(r"^source-", "", b)
    return re.sub(r"\.pptx$", "", b, flags=re.I)


TEMPLATE_FILE = "模板.pptx"


def template_source_pptx(t):
    """模板源 PPT：优先 模板.pptx，兼容旧的 source-*.pptx，再退到目录里任意一个 .pptx"""
    d = t.get("_dir") if isinstance(t, dict) else None
    if not d or not os.path.isdir(d):
        return None
    names = sorted(os.listdir(d))
    p = os.path.join(d, TEMPLATE_FILE)
    if os.path.isfile(p):
        return p
    for pat in (r"^source-.*\.pptx$", r"^[^~].*\.pptx$"):
        for n in names:
            if re.match(pat, n, re.I):
                return os.path.join(d, n)
    return None


def list_templates(extra=None, include_builtin=True):
    custom = stored_templates(extra)
    if not include_builtin:
        return custom
    return custom + builtin_themes()


def get_template(want=None, extra=None):
    """id 精确匹配 > 源 PPT 文件名包含关键字 > 名称包含；没给就用默认通用风格"""
    if isinstance(want, dict):
        return want
    if not want or want == "default":
        return copy.deepcopy(DEFAULT_THEME)
    for t in builtin_themes():
        if t["id"] == want:
            return t
    stored = stored_templates(extra)
    for t in stored:
        if t["id"] == want:
            return t
    for t in stored:
        if want in source_name(t) or want in (t.get("name") or ""):
            return t
    return None


def asset_path(theme, rel):
    """模板提取图片的绝对路径（templates/<id>/assets/<rel>）"""
    d = theme.get("_dir")
    if not d or not rel:
        return None
    p = os.path.normpath(os.path.join(d, "assets", rel))
    return p if os.path.isfile(p) else None
