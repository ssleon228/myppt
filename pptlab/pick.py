"""选系统模板：按内容推荐 3 套（程序定），每套出一张「封面 + 内容页」缩略图给用户挑；用户不选就用第一套。

系统模板 = 6 种风格（封面构图 + 设计语言配套）× 12 套色板 = 72 套。
  python -m pptlab.pick deck.json                列出推荐的 3 套（和全部 72 套的编号）
  python -m pptlab.pick deck.json --preview 目录  另外每套生成一份 2 页的预览 pptx（有 soffice 时顺便转成图片）
选定后把 brand 写进 deck.json 顶层："brand": {"cover": "...", "palette": "..."}
"""
import json
import os
import shutil
import subprocess
import sys

from .brand import COVERS
from .palette import PALETTES
from .styles import COVER_LANG, LANGS
from .enrich import detect_scenario

# 场景 → 合适的风格（靠前的更合适）
SCENE_STYLE = {
    "report": ("diagonal", "arcs", "frame", "band", "split", "mosaic"),
    "plan": ("mosaic", "band", "diagonal", "split", "arcs", "frame"),
    "project": ("split", "mosaic", "diagonal", "arcs", "band", "frame"),
    "problem": ("arcs", "diagonal", "band", "frame", "split", "mosaic"),
    "summary": ("band", "diagonal", "frame", "split", "arcs", "mosaic"),
    "training": ("split", "arcs", "mosaic", "diagonal", "band", "frame"),
}
STYLE_KW = {"mosaic": ("科技", "数字化", "智能", "系统", "数据", "平台", "AI"), "frame": ("高端", "私行", "财富", "典礼", "年会"),
            "band": ("冲刺", "动员", "誓师", "攻坚", "营销"), "split": ("客户", "服务", "零售", "体验", "培训"),
            "arcs": ("研究", "分析", "报告", "观察"), "diagonal": ("经营", "业绩", "汇报", "季度")}


def all_templates():
    """→ 72 套：[(编号, cover, palette)]"""
    out = []
    n = 0
    for c in COVERS:
        for p in PALETTES:
            n += 1
            out.append((n, c, p))
    return out


def recommend(text, k=3):
    """→ [{no, cover, palette, style, name, why}]，3 套风格互不相同"""
    sid, _ = detect_scenario(text)
    base = list(SCENE_STYLE.get(sid, SCENE_STYLE["report"]))
    kw_score = {c: sum(1 for w in ws if w in text) for c, ws in STYLE_KW.items()}
    order = sorted(base, key=lambda c: (-kw_score.get(c, 0), base.index(c)))
    # 色板：气质词命中多的优先；同一套色板不重复
    pal_rank = sorted(PALETTES, key=lambda pid: -sum(1 for w in PALETTES[pid]["mood"].split() if w in text))
    default_for = {"diagonal": "navy-gold", "split": "teal-coral", "arcs": "charcoal-teal", "band": "ink-red",
                   "frame": "burgundy-sand", "mosaic": "indigo-cyan"}
    nos = {(c, p): n for n, c, p in all_templates()}
    out, used = [], set()
    for c in order[:k]:
        hit = [pid for pid in pal_rank if pid not in used and sum(1 for w in PALETTES[pid]["mood"].split() if w in text)]
        pid = hit[0] if hit else (default_for[c] if default_for[c] not in used else next(p for p in PALETTES if p not in used))
        used.add(pid)
        lang = COVER_LANG[c]
        why = []
        if kw_score.get(c):
            why.append("内容里有“%s”" % next(w for w in STYLE_KW[c] if w in text))
        if hit:
            why.append("色板气质：%s" % PALETTES[pid]["mood"])
        out.append({"no": nos[(c, pid)], "cover": c, "palette": pid, "style": LANGS[lang]["name"],
                    "name": "%s · %s" % (LANGS[lang]["name"], PALETTES[pid]["name"]), "why": "；".join(why) or "适合这类汇报"})
    return out


def preview(deck, rec, outdir):
    """每套推荐生成 2 页预览（封面 + 第一个内容页）→ [(推荐, pptx 路径, 图片路径或 None)]"""
    from .render import render_deck_file
    pages = deck.get("pages") or [p for c in deck.get("chapters") or [] for p in c.get("pages") or []]
    cover = next((p for p in pages if p.get("type") == "cover"), {"type": "cover", "title": deck.get("title") or "演示文稿"})
    content = next((p for p in pages if p.get("type") not in ("cover", "chapter", "toc", "end")), None)
    os.makedirs(outdir, exist_ok=True)
    out = []
    for r in rec:
        mini = {"pages": [cover] + ([content] if content else []), "brand": {"cover": r["cover"], "palette": r["palette"]}}
        src = os.path.join(outdir, "mini-%d.json" % r["no"])
        json.dump(mini, open(src, "w", encoding="utf-8"), ensure_ascii=False)
        pp = os.path.join(outdir, "模板%d-%s.pptx" % (r["no"], r["name"].replace(" · ", "-")))
        render_deck_file(src, pp)
        os.remove(src)
        img = None
        if shutil.which("soffice") and shutil.which("pdftoppm"):
            try:
                subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", outdir, pp],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                pdf = pp[:-5] + ".pdf"
                subprocess.run(["pdftoppm", "-r", "36", "-png", pdf, pp[:-5]], timeout=60)
                pngs = sorted(f for f in os.listdir(outdir) if f.startswith(os.path.basename(pp[:-5])) and f.endswith(".png"))
                if pngs and shutil.which("montage"):
                    img = pp[:-5] + ".jpg"
                    subprocess.run(["montage"] + [os.path.join(outdir, f) for f in pngs] +
                                   ["-tile", "2x", "-geometry", "+4+4", img], timeout=60)
                    for f in pngs:
                        os.remove(os.path.join(outdir, f))
                elif pngs:
                    img = os.path.join(outdir, pngs[0])
                os.remove(pdf)
            except Exception:  # noqa: BLE001  预览图只是方便看，失败不影响
                img = None
        out.append((r, pp, img))
    return out


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a:
        print(__doc__)
        return 2
    deck = json.load(open(a[0], encoding="utf-8"))
    text = json.dumps(deck, ensure_ascii=False)[:4000]
    rec = recommend(text)
    print("推荐（不选就用第 1 套）：")
    for i, r in enumerate(rec, 1):
        print("  %d. 模板 %d：%s（%s）—— %s" % (i, r["no"], r["name"], r["cover"] + "/" + r["palette"], r["why"]))
    if "--all" in a:
        print("\n全部 72 套：")
        for n, c, p in all_templates():
            print("  %2d. %s · %s（%s/%s）" % (n, LANGS[COVER_LANG[c]]["name"], PALETTES[p]["name"], c, p))
    if "--preview" in a:
        d = a[a.index("--preview") + 1]
        for r, pp, img in preview(deck, rec, d):
            print("预览：%s%s" % (pp, ("，图片 " + img) if img else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
