"""内容自动丰富：程序定框架、程序算数、程序查，模型只负责按框架写。

流程里的位置：收集材料之后、列大纲之前。
  1. detect_scenario：按标题和材料里的词判断是哪类汇报（程序定，模型可以改）
  2. framework：这类汇报该有哪些部分、每部分要写到什么程度（给模型的写作要求）
  3. compute：能算的数由程序算（增幅、完成率、占比、差距），模型直接引用，不自己算
  4. check：写完后程序检查 —— 空话套话、要点没有具体内容、数字在材料里找不到出处、框架缺部分
  5. clean：模型在稿子里用【待补：…】【需核实：…】做标记；程序把标记从 PPT 文字里去掉，
     整理成「待补 / 需核实」清单（带页码、位置），在聊天里交给用户。PPT 上不出现任何标记和来源。
"""
import json
import re
import sys

# ════════════════ 场景框架 ════════════════
SCENARIOS = {
    "report": dict(name="业务汇报 / 经营分析", kw=("汇报", "经营", "业绩", "季度", "月度", "半年", "年度", "情况", "分析会", "例会"),
                   sections=[
                       ("总体情况", "先给结论：核心指标完成了多少、和目标/去年/上期比怎样。用指标页或图表页", ("stats", "kpi", "chart")),
                       ("亮点", "哪些做得好，好在哪里，靠什么做到的（具体举措、具体机构或产品）", ("bullets", "columns", "iconlist")),
                       ("问题与差距", "哪些没做好、落后多少；不回避，写清楚差距的数", ("compare", "table", "bullets")),
                       ("原因分析", "每个问题对应原因：外部（市场、政策）和内部（产品、流程、队伍）分开写", ("matrix", "columns", "bullets")),
                       ("下一步措施", "针对原因的措施：做什么、谁负责、什么时候完成、预期效果", ("steps", "timeline", "table")),
                   ]),
    "plan": dict(name="工作计划 / 规划", kw=("计划", "规划", "目标", "思路", "部署", "明年", "下半年", "2027", "三年"),
                 sections=[
                     ("回顾与起点", "现在在哪里：上一阶段结果和现有基础，用数说话", ("stats", "chart")),
                     ("目标", "要到哪里：量化目标，和现状的差距", ("kpi", "stats")),
                     ("重点任务", "怎么去：分几条线，每条线做什么", ("columns", "iconlist", "steps")),
                     ("时间安排", "什么时候做到：里程碑", ("timeline", "steps")),
                     ("保障措施", "需要什么支持：人、钱、系统、机制；风险和应对", ("bullets", "matrix")),
                 ]),
    "project": dict(name="项目方案 / 立项", kw=("方案", "项目", "立项", "合作", "上线", "建设", "试点"),
                    sections=[
                        ("背景与必要性", "为什么要做：问题或机会，不做的代价", ("bullets", "quote")),
                        ("方案内容", "做什么、怎么做：产品/流程/系统的关键设计", ("columns", "iconlist", "steps")),
                        ("效益测算", "做了能带来什么：规模、收入、成本、风险的变化（数由程序算）", ("stats", "table", "chart")),
                        ("风险与应对", "可能出什么问题，怎么防", ("matrix", "compare", "table")),
                        ("实施计划与资源", "分几步、各需要什么资源、请领导决策什么", ("timeline", "steps")),
                    ]),
    "problem": dict(name="专项问题分析", kw=("问题", "整改", "风险", "不良", "投诉", "专项", "排查", "原因"),
                    sections=[
                        ("问题现状", "问题有多大：数量、金额、趋势、分布", ("stats", "chart", "table")),
                        ("原因剖析", "为什么会这样：分层找原因，直接原因和根本原因", ("matrix", "columns")),
                        ("影响评估", "不解决会怎样", ("bullets", "compare")),
                        ("整改措施", "怎么改：每条措施对应原因，有责任人和时限", ("table", "steps")),
                        ("长效机制", "怎么防止再犯：制度、系统、考核", ("iconlist", "bullets")),
                    ]),
    "summary": dict(name="工作总结 / 述职", kw=("总结", "述职", "回顾", "竞聘", "年终"),
                    sections=[
                        ("主要成绩", "做成了什么：关键数字和代表性案例", ("stats", "kpi")),
                        ("重点工作", "分几块做了哪些事，每块的结果", ("columns", "iconlist")),
                        ("不足与反思", "哪里没做好，学到了什么", ("bullets", "compare")),
                        ("下一步打算", "接下来怎么做", ("steps", "timeline")),
                    ]),
    "training": dict(name="培训 / 产品介绍", kw=("培训", "介绍", "宣讲", "课件", "产品手册", "指引", "解读"),
                     sections=[
                         ("是什么", "一句话讲清楚，再讲关键特点", ("quote", "iconlist")),
                         ("为什么", "给谁用、解决什么问题、和别的比好在哪", ("compare", "columns")),
                         ("怎么用", "步骤、条件、注意事项", ("steps", "table")),
                         ("常见问题", "用户最常问的几个问题和回答", ("faq",)),
                     ]),
}

VAGUE = ("进一步", "持续", "大力", "积极", "稳步", "有效", "显著", "加强", "不断", "全面", "深入", "切实", "扎实", "着力",
         "努力", "推进", "提升", "优化", "完善", "强化", "多措并举", "取得了一定", "较好", "良好", "明显")
CONCRETE = re.compile(r"\d|[A-Z]{2,}|“|「|《|分行|支行|部门|系统|产品|客户|渠道|合同|项目|模型|平台|月|季度|年")
MARK = re.compile(r"【(待补|需核实)[:：]?([^】]*)】")
NUM = re.compile(r"[+\-−]?\d[\d,]*(?:\.\d+)?")


def detect_scenario(text):
    """→ (场景 id, 命中的词)。按关键词计分，同分取靠前的；什么都没命中按业务汇报"""
    text = text or ""
    best, hits = "report", []
    best_n = 0
    for sid, sc in SCENARIOS.items():
        h = [k for k in sc["kw"] if k in text]
        if len(h) > best_n:
            best, hits, best_n = sid, h, len(h)
    return best, hits


def framework(sid, has_material=True, can_search=False):
    """给模型的写作要求（内部提示词）"""
    sc = SCENARIOS.get(sid) or SCENARIOS["report"]
    lines = ["这是一份「%s」。按下面的框架组织内容，每部分都要写到，可以合并或拆页：" % sc["name"]]
    for i, (name, need, types) in enumerate(sc["sections"], 1):
        lines.append("%d. %s：%s（适合的页型：%s）" % (i, name, need, "、".join(types)))
    lines += [
        "",
        "写作规则（程序会逐条检查，不合格会退回）：",
        "· 每条要点要有具体内容：数字、机构、产品、动作、时间，至少一样；不要只写“进一步加强”“持续提升”这类空话。",
        "· 先结论后展开：页标题就是这一页的结论，一句话，带关键数字。",
        "· 每个内容页加一个 \"section\" 字段，写它属于框架里的哪一部分（如 \"section\": \"原因分析\"），程序用它检查有没有漏部分。",
        "· 增幅、完成率、占比、差距这些数，用程序算好的结果（见“程序算好的数”），不要自己算。",
        "· 数字只能来自用户材料%s。材料里没有的数字不要编：这句话改成不带数字的说法，并在后面加【待补：缺什么】。"
        % ("或搜索结果（记下来源网址，放在 sources 里）" if can_search else ""),
        "· 凭自己的知识写的行业数字、政策条文，后面加【需核实：核实什么】。",
        "· 【待补】【需核实】只是给程序的标记，程序会把它们从 PPT 上去掉，整理成清单交给用户。",
    ]
    if not has_material:
        lines += ["", "用户没有提供材料：%s" % (
            "先联网搜集公开资料（行业数据、政策、同业做法），每条记下来源；单位内部数据搜不到，全部按【待补】处理。" if can_search else
            "不能联网，就用通用的分析框架和行业常识把结构和思路写完整；所有具体数字都按【待补】或【需核实】处理。")]
    return "\n".join(lines)


# ════════════════ 程序算数 ════════════════

def _f(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = NUM.search(str(v).replace("−", "-"))
    return float(m.group(0).replace(",", "")) if m else None


def _fmt(x, nd=1):
    s = ("%." + str(nd) + "f") % x
    return s.rstrip("0").rstrip(".") if "." in s else s


def compute(facts):
    """facts: [{name, value, unit?, prev?, last_year?, target?, total?}] → [{name, text, kind}]
    prev=上期，last_year=去年同期，target=目标，total=总量（算占比）。百分比指标的变化用“个百分点”。"""
    out = []
    for f in facts or []:
        v = _f(f.get("value"))
        if v is None:
            continue
        name, unit = f.get("name") or "", f.get("unit") or ""
        pct = unit.strip() == "%" or str(f.get("value")).strip().endswith("%")
        for key, label in (("prev", "较上期"), ("last_year", "同比")):
            b = _f(f.get(key))
            if b is None:
                continue
            if pct:
                d = v - b
                out.append({"name": name, "kind": key, "text": "%s%s%s %s 个百分点" % (name, label, "上升" if d >= 0 else "下降",
                                                                               _fmt(abs(d), 2))})
            elif b:
                r = (v - b) / abs(b) * 100
                out.append({"name": name, "kind": key, "text": "%s%s%s %s%%（%s → %s%s）" % (
                    name, label, "增长" if r >= 0 else "下降", _fmt(abs(r)), _fmt(b, 2), _fmt(v, 2), unit)})
        t = _f(f.get("target"))
        if t:
            r = v / t * 100
            gap = t - v
            txt = "%s完成目标的 %s%%" % (name, _fmt(r))
            if gap > 0 and not pct:
                txt += "，还差 %s%s" % (_fmt(gap, 2), unit)
            out.append({"name": name, "kind": "target", "text": txt})
        tot = _f(f.get("total"))
        if tot:
            out.append({"name": name, "kind": "share", "text": "%s占总量的 %s%%" % (name, _fmt(v / tot * 100))})
    return out


# ════════════════ 检查 ════════════════

def _texts(page):
    """页面里所有文字 → [(位置说明, 文字)]"""
    out = []

    def walk(v, path):
        if isinstance(v, str):
            if v.strip():
                out.append((path, v))
        elif isinstance(v, dict):
            for k, x in v.items():
                if k in ("type", "variant", "icon", "style", "chart") and not isinstance(x, (dict, list)):
                    continue
                walk(x, path + "." + k if path else k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, "%s[%d]" % (path, i + 1))
    walk(page, "")
    return out


_POS = {"title": "标题", "subtitle": "副标题", "items": "要点", "takeaways": "结论", "stats": "指标", "cols": "栏",
        "iconItems": "图标项", "steps": "步骤", "callout": "结论条", "heading": "小标题", "text": "正文", "desc": "说明",
        "label": "标签", "value": "数值", "rows": "表格", "headers": "表头", "left": "左栏", "right": "右栏", "points": "要点",
        "timeline": "时间轴", "quadrants": "象限", "quote": "引言", "faq": "问答", "q": "问题", "a": "回答", "groups": "分组",
        "layout": "版面", "children": "", "chart": "图表"}


def where(path):
    """items[2].text → 要点第 2 条 正文"""
    parts = []
    for seg in path.split("."):
        m = re.match(r"(\w+)((?:\[\d+\])*)", seg)
        if not m:
            continue
        name = _POS.get(m.group(1), m.group(1))
        idx = re.findall(r"\[(\d+)\]", m.group(2))
        if name:
            parts.append(name + ("第 %s 条" % idx[-1] if idx else ""))
        elif idx:
            parts.append("第 %s 条" % idx[-1])
    return " ".join(parts) or "正文"


def _num_ok(n, material_nums, computed_nums):
    if n in material_nums or n in computed_nums:
        return True
    try:
        x = float(n)
    except ValueError:
        return True
    if x == int(x) and (1990 <= x <= 2100 or x <= 12):  # 年份、月份、序号
        return True
    for m in material_nums | computed_nums:
        try:
            if abs(float(m) - x) < 1e-9:
                return True
        except ValueError:
            pass
    return False


def _nums(text):
    return set(m.group(0).replace(",", "").lstrip("+").replace("−", "-") for m in NUM.finditer(text or ""))


def check(deck, material="", computed=(), scenario=None, sources=()):
    """→ {"issues": [(页, 位置, 问题)], "todo": [...], "verify": [...], "missing_sections": [...]}
    material：用户材料和搜索结果的原文；computed：compute() 的结果；sources：搜索来源（只给聊天用）"""
    pages = deck.get("pages") or [p for c in deck.get("chapters") or [] for p in c.get("pages") or []]
    mat = _nums(material)
    for s in sources or ():
        mat |= _nums(s.get("text") or s.get("claim") or "")
    comp = set()
    for c in computed or ():
        comp |= _nums(c.get("text"))
    issues, todo, verify = [], [], []
    for pi, page in enumerate(pages, 1):
        if page.get("type") in ("cover", "end", "toc", "chapter"):
            continue
        for path, t in _texts(page):
            pos = where(path)
            for m in MARK.finditer(t):
                (todo if m.group(1) == "待补" else verify).append(
                    {"page": pi, "title": page.get("title") or "", "where": pos, "what": m.group(2).strip() or "数据",
                     "context": MARK.sub("", t).strip()[:40]})
            clean = MARK.sub("", t)
            vague = [w for w in VAGUE if w in clean]
            if path.split(".")[-1].split("[")[0] in ("items", "points", "text", "desc", "a") or "items" in path:
                if len(clean) >= 6 and vague and not CONCRETE.search(clean):
                    issues.append((pi, pos, "空话：“%s”只有“%s”这类词，没有具体内容" % (clean[:30], "、".join(vague[:3]))))
            if "【需核实" not in t:  # 标了需核实的数字不追出处
                bad = [n for n in _nums(clean) if not _num_ok(n, mat, comp)]
                if bad:
                    issues.append((pi, pos, "数字 %s 在材料里找不到出处，删掉或标【待补】/【需核实】" % "、".join(sorted(bad)[:4])))
    missing = []
    if scenario in SCENARIOS:
        alltext = json.dumps(deck, ensure_ascii=False)
        for name, need, types in SCENARIOS[scenario]["sections"]:
            keys = [k for k in re.split(r"[与/、 ]", name) if k]
            tagged = any(p.get("section") and (p["section"] == name or any(k in p["section"] for k in keys)) for p in pages)
            if not tagged and not any(k in alltext for k in keys):
                missing.append(name)
    return {"issues": issues, "todo": todo, "verify": verify, "missing_sections": missing}


def clean(deck):
    """去掉稿子里所有【待补】【需核实】标记（PPT 上不出现），返回新 deck；标记里的内容不保留"""
    def walk(v):
        if isinstance(v, str):
            s = MARK.sub("", v)
            s = re.sub(r"[ \t]{2,}", " ", s)
            s = re.sub(r"\s+([，。；、])", r"\1", s)
            return s.strip() if s != v else v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items() if k not in ("sources", "section", "scenario")}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v
    return walk(deck)


def report_text(res, sources=()):
    """交付时在聊天里给用户的清单"""
    out = []
    if res["todo"]:
        out.append("待补（PPT 上没写数字的地方，补上数据后可以再让我更新）：")
        for t in res["todo"]:
            out.append("  · 第 %d 页「%s」%s：缺 %s" % (t["page"], t["title"][:18], t["where"], t["what"]))
    if res["verify"]:
        out.append("需核实（内容已写进 PPT，建议核对）：")
        for t in res["verify"]:
            out.append("  · 第 %d 页「%s」%s：%s" % (t["page"], t["title"][:18], t["where"], t["what"] or t["context"]))
    if sources:
        out.append("自动搜集的资料来源：")
        for s in sources:
            out.append("  · %s%s" % ((("第 %s 页 " % s["page"]) if s.get("page") else ""), s.get("url") or s.get("name") or ""))
    return "\n".join(out) or "没有待补或需核实的内容。"


def main(argv=None):
    """python -m pptlab.enrich framework "标题和材料摘要" [--no-material] [--search]
       python -m pptlab.enrich compute facts.json
       python -m pptlab.enrich check deck.json [--material 材料.txt] [--facts facts.json] [--clean 输出.json]"""
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 2 and a[0] == "framework":
        sid, hits = detect_scenario(a[1])
        print("场景：%s（命中：%s）\n" % (SCENARIOS[sid]["name"], "、".join(hits) or "无，按业务汇报"))
        print(framework(sid, "--no-material" not in a, "--search" in a))
        return 0
    if len(a) >= 2 and a[0] == "compute":
        for c in compute(json.load(open(a[1], encoding="utf-8"))):
            print(c["text"])
        return 0
    if len(a) >= 2 and a[0] == "check":
        deck = json.load(open(a[1], encoding="utf-8"))
        opt = dict(zip(a[2::2], a[3::2]))
        material = open(opt["--material"], encoding="utf-8").read() if "--material" in opt else ""
        comp = compute(json.load(open(opt["--facts"], encoding="utf-8"))) if "--facts" in opt else []
        title = " ".join(p.get("title") or "" for p in (deck.get("pages") or [])[:3])
        sid = deck.get("scenario") or detect_scenario(title + material[:2000])[0]
        res = check(deck, material, comp, sid, deck.get("sources") or ())
        for pi, pos, msg in res["issues"]:
            print("问题  第 %d 页 %s：%s" % (pi, pos, msg))
        for m in res["missing_sections"]:
            print("缺部分  「%s」（%s 框架要求）" % (m, SCENARIOS[sid]["name"]))
        print()
        print(report_text(res, deck.get("sources") or ()))
        if "--clean" in opt:
            json.dump(clean(deck), open(opt["--clean"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("\n已去掉标记和来源，另存为 %s（拿这份去生成 PPT）" % opt["--clean"])
        return 1 if res["issues"] else 0
    print(main.__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
