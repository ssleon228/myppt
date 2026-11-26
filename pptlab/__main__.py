"""python -m pptlab deck.json out.pptx [--off] [--json] [--cover=.. --palette=.. --mood=.. --primary=.. --pattern=.. --banner=.. --org=..]

带 --cover/--palette 等参数，或 deck.json 顶层有 "brand" 时，用 AI 设计的模板（程序画）；否则用 deck 指定的现成模板。"""
import json
import sys

from .render import render_deck_file


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in a
    off = "--off" in a
    brand = {}
    for x in a:
        if x.startswith("--") and "=" in x:
            k, v = x[2:].split("=", 1)
            if k in ("cover", "palette", "mood", "primary", "pattern", "banner", "org", "logo", "image", "motif"):
                brand[k] = v
    a = [x for x in a if not x.startswith("--")]
    if len(a) < 2:
        print(__doc__)
        return 1
    try:
        opts = {"design": "off" if off else "auto"}
        if brand:
            opts["brand"] = brand
        info = render_deck_file(a[0], a[1], options=opts)
    except Exception as e:  # noqa: BLE001
        from .engine.api import DeckError
        if isinstance(e, DeckError):
            print("内容不合规：", e)
            return 2
        raise
    if as_json:
        print(json.dumps(info, ensure_ascii=False))
    else:
        for p in info["pages"]:
            line = "%2d %-9s %-22s %s" % (p["page"], p["type"], p.get("source", ""), p["title"][:24])
            if "level" in p:
                line += "  [字号档%d 填充%d%%]" % (p["level"], round(p["fill"] * 100))
            print(line)
            for w in p.get("warnings") or []:
                print("     ! " + w)
            for n in p.get("notes") or []:
                print("     · " + n)
        for n in info.get("brand") or []:
            print("模板：" + n)
        for w in info["warnings"]:
            print("提示：" + w)
        print("输出：" + info["output"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
