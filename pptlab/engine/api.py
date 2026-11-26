"""对外 API：校验 / 渲染 deck。

    from pptlab.engine import api
    errors = api.validate_deck(doc)                   # [] 表示通过
"""
import json
import os
import re

from . import fontmetrics
from .normalize import normalize_pages
from .schema import validate_pages
from .themes import get_template, list_templates as _list_templates, source_name
from .variants import resolve_variants, VARIANT_LABELS

DEFAULT_TEMPLATE = "default"

_FENCE = re.compile(r"^[\s\S]*?```(?:json)?\s*\n([\s\S]*?)\s*```[\s\S]*$")


class DeckError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join("%s %s" % (e.get("path", ""), e.get("message", "")) for e in errors[:5]))


def parse_deck_text(raw):
    """容错解析：去 BOM、剥 ```json 代码块；顶层是数组时当作 pages"""
    body = raw.lstrip("﻿")
    m = _FENCE.match(body)
    if m:
        body = m.group(1)
    doc = json.loads(body)
    if isinstance(doc, list):
        doc = {"pages": doc}
    if not isinstance(doc, dict):
        raise ValueError("顶层应为对象 {title, pages}")
    return doc


def prepare(doc):
    """规范化 + 校验 → (pages, errors)"""
    pages = normalize_pages(doc.get("pages") or [])
    if not pages:
        return pages, [{"path": "pages", "message": "没有页面"}]
    return pages, validate_pages(pages)


def validate_deck(doc):
    return prepare(doc)[1]


def load_template(want=None, extra_dirs=None):
    return get_template(want, extra_dirs) or get_template("default")


def list_templates(extra_dirs=None, include_builtin=True):
    return _list_templates(extra_dirs, include_builtin)


def font_report(theme, fonts=None):
    """取模板字体 → (cn, latin, warnings)。不要求安装任何字体：本机没有时排版按内置通用字宽近似，
    打开 PPT 的电脑没有这个字体会自动换成同类字体，所以不提示。"""
    cfg = dict((theme or {}).get("fonts") or {})
    if fonts:
        cfg.update({k: v for k, v in fonts.items() if v})
    cn = cfg.get("cn") or (theme or {}).get("font") or "微软雅黑"
    return cn, cfg.get("latin"), []


def render_deck(pages, template=None, title=None, options=None):
    """pages（原始或已规范化）→ (pptx bytes, info)。校验不过抛 DeckError。"""
    from .ooxml.package import Presentation
    from .render import render_pages, PAGE_W, PAGE_H

    options = dict(options or {})
    doc_pages, errors = prepare({"pages": pages})
    if errors:
        raise DeckError(errors)
    theme = template if isinstance(template, dict) else load_template(template, options.get("templateDirs"))
    cn, latin, warns = font_report(theme, options.get("fonts"))
    title = title or next((p.get("title") for p in doc_pages if p.get("type") == "cover" and p.get("title")), None) or "演示文稿"
    pres = Presentation(PAGE_W / 144.0, PAGE_H / 144.0, title=title, theme_colors=theme.get("colors"), font=cn,
                        font_hei=(theme.get("fonts") or {}).get("hei") or theme.get("fontHei") or "黑体")
    pres.autofit = options.get("autofit", True) is not False and os.environ.get("PPT_AUTOFIT") != "off"
    warns += render_pages(pres, doc_pages, theme, options)
    data = pres.to_bytes()
    variants = resolve_variants(doc_pages) if str(options.get("variants", "auto")) != "off" else ["default"] * len(doc_pages)
    info = {
        "template": theme.get("id"),
        "templateName": source_name(theme) or theme.get("name"),
        "title": title,
        "pages": [{"type": p.get("type"), "variant": None if variants[i] == "default" else VARIANT_LABELS.get(variants[i]),
                   "title": p.get("title") or ""} for i, p in enumerate(doc_pages)],
        "warnings": warns + list(pres.warnings),
    }
    return data, info


def render_deck_file(in_path, out_path, template=None, options=None):
    """deck.json → out.pptx。相对图片路径按 deck.json 所在目录解析。"""
    if in_path == "-":
        import sys
        raw = sys.stdin.read()
        base = os.getcwd()
    else:
        with open(in_path, encoding="utf-8-sig") as f:
            raw = f.read()
        base = os.path.dirname(os.path.abspath(in_path))
    doc = parse_deck_text(raw)
    options = dict(options or {})
    options.setdefault("baseDir", base)
    for k in ("variants", "icons", "fonts", "noPageFooter"):
        if k in doc and k not in options:
            options[k] = doc[k]
    data, info = render_deck(doc.get("pages") or [], template or doc.get("template"), doc.get("title"), options)
    d = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(out_path, "wb") as f:
        f.write(data)
    info["output"] = os.path.abspath(out_path)
    return info
