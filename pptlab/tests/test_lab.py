"""pptlab（实验版：程序/AI 设计版面）测试"""
import io
import json
import re
import os
import unittest
import zipfile

from pptlab import render as R, measure
from pptlab.spec import normalize
from pptlab.solver import Solver
from pptlab.engine import render as PR, api

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(HERE, "..", "examples")
SAMPLE = os.path.join(EX, "sample-deck.json")


def setUpModule():
    PR.apply_theme(api.load_template())
    measure.set_fonts(PR.K.FONT, PR.K.LATIN)


class SpecTest(unittest.TestCase):
    def test_fixes_bad_tokens_and_drops_coords(self):
        tree, fixes, errors = normalize({"box": "row", "gap": "huge", "children": [
            {"el": "text", "text": "a", "x": 100, "fontSize": 40, "color": "#FF0000"},
            {"el": "stat", "value": "12%", "label": "增速"}]})
        self.assertFalse(errors)
        self.assertEqual(tree["gap"], "m")
        self.assertEqual(tree["children"][1]["el"], "kpi")
        self.assertNotIn("x", tree["children"][0])
        self.assertTrue(any("坐标" in f for f in fixes))

    def test_unknown_element_is_error(self):
        _, _, errors = normalize({"box": "col", "children": [{"el": "hologram", "text": "x"}]})
        self.assertTrue(errors)

    def test_wide_row_becomes_grid(self):
        tree, fixes, _ = normalize({"box": "row", "children": [{"el": "kpi", "value": str(i)} for i in range(6)]})
        self.assertEqual(tree["box"], "col")
        self.assertEqual(len(tree["children"]), 2)


class SolverTest(unittest.TestCase):
    def test_little_text_grows(self):
        t, _, _ = normalize({"box": "col", "children": [{"el": "bullets", "items": ["短句一", "短句二"]}]})
        self.assertEqual(Solver(t).solve()["level"], 6)

    def test_lots_of_text_shrinks_or_fails(self):
        long = "这是一段很长的说明文字，" * 12
        t, _, _ = normalize({"box": "col", "children": [{"el": "bullets", "items": [long] * 6}]})
        r = Solver(t).solve()
        self.assertTrue(not r["ok"] or r["level"] < 2)

    def test_everything_inside_area(self):
        t, _, _ = normalize({"box": "row", "children": [
            {"el": "kpi", "value": "86.4亿元", "label": "余额", "style": "accent"},
            {"box": "col", "children": [{"el": "heading", "text": "标题"}, {"el": "bullets", "items": ["a", "b", "c"]}]}]})
        r = Solver(t).solve()
        a = r["area"]
        for n, (x, y, w, h), tone, nat in r["leaves"]:
            self.assertGreaterEqual(y, a["y"] - 1)
            self.assertLessEqual(y + h, a["y"] + a["h"] + 1)
            self.assertLessEqual(x + w, a["x"] + a["w"] + 1)


class DeckTest(unittest.TestCase):
    def test_sample_deck(self):
        with open(SAMPLE, encoding="utf-8") as f:
            doc = json.load(f)
        data, info = R.render_deck(doc["pages"], doc.get("template"), doc.get("title"))
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(len([n for n in z.namelist() if n.startswith("ppt/slides/slide")]), len(doc["pages"]))
        srcs = [p["source"] for p in info["pages"]]
        self.assertIn("AI版面", srcs)
        self.assertTrue(any(s.startswith("程序设计") for s in srcs))

    def test_bad_ai_layout_falls_back(self):
        long = "超长的内容" * 300
        pages = [{"type": "free", "title": "坏版面", "layout": {"box": "col", "children": [
            {"el": "text", "text": long, "role": "lead"}, {"el": "text", "text": long}]}}]
        data, info = R.render_deck(pages)
        self.assertNotEqual(info["pages"][0]["source"], "AI版面")


if __name__ == "__main__":
    unittest.main()


class BrandTest(unittest.TestCase):
    def test_palettes_pass_contrast(self):
        from pptlab.palette import PALETTES, build, contrast
        for pid in list(PALETTES) + [None]:
            for spec in ({"palette": pid} if pid else {"primary": "FFE680"}, {"primary": "33CC33"}, {"primary": "777777"}):
                pal, _ = build(spec)
                self.assertGreaterEqual(contrast("FFFFFF", pal["primary"]), 4.5, spec)
                self.assertGreaterEqual(contrast(pal["ink"], "FFFFFF"), 12, spec)
                self.assertGreaterEqual(contrast(pal["muted"], "FFFFFF"), 4.5, spec)

    def test_mood_picks_palette(self):
        from pptlab.palette import pick_by_mood
        self.assertEqual(pick_by_mood("党建 政务"), "ink-red")
        self.assertEqual(pick_by_mood("科技 数字化"), "indigo-cyan")

    def test_bad_choices_fall_back(self):
        from pptlab.brand import Brand, COVERS
        b = Brand({"cover": "spaceship", "pattern": "plaid", "palette": "nope", "logo": "missing.png"}, "标题")
        self.assertIn(b.cover, COVERS)
        self.assertTrue(any("找不到" in n for n in b.notes))

    def test_all_covers_render(self):
        from pptlab.brand import COVERS
        with open(SAMPLE, encoding="utf-8") as f:
            doc = json.load(f)
        for c in COVERS:
            data, info = R.render_deck(doc["pages"], None, doc.get("title"), brand={"cover": c, "org": "测试部"})
            self.assertTrue(zipfile.ZipFile(io.BytesIO(data)).testzip() is None)
            self.assertTrue(info["brand"])


class StyleTest(unittest.TestCase):
    def test_languages_choose_different_compositions(self):
        with open(SAMPLE, encoding="utf-8") as f:
            doc = json.load(f)
        picks = {}
        for c in ("diagonal", "arcs", "band", "mosaic"):
            _, info = R.render_deck(doc["pages"], None, doc.get("title"), brand={"cover": c})
            picks[c] = tuple(p.get("source") for p in info["pages"])
        self.assertEqual(len(set(picks.values())), len(picks))


class FlairTest(unittest.TestCase):
    """第四批：从人工模板里学来的、机器能自动做的设计手法"""

    def test_number_highlight(self):
        from pptlab.blocks import hl_runs
        r = hl_runs("新签 4S 店 37 家，2026 年放款 12.6 亿元，占 58%", "000000", "FF0000")
        bold = [x["text"].strip() for x in r if x["options"].get("bold")]
        self.assertEqual(bold, ["37 家", "12.6 亿元", "58%"])
        self.assertIsNone(hl_runs("没有数字", "000000", "FF0000"))

    def test_emphasize_first_kpi(self):
        from pptlab import styles as STY
        STY.use("corporate")
        t = {"box": "row", "children": [{"el": "kpi", "value": "1", "style": "soft"} for _ in range(3)]}
        STY.emphasize(t)
        self.assertEqual([c["style"] for c in t["children"]], ["accent", "soft", "soft"])
        STY.use("editorial")
        t = {"box": "row", "children": [{"el": "kpi", "value": "1", "style": "soft"} for _ in range(3)]}
        STY.emphasize(t)
        self.assertEqual(t["children"][0]["style"], "soft")
        STY.use("corporate")

    def test_orbs_and_seq(self):
        from pptlab.solver import Solver
        from pptlab.spec import normalize
        t, _, er = normalize({"box": "col", "children": [{"el": "orbs", "items": [{"head": "甲", "text": "一"}] * 4}]})
        self.assertFalse(er)
        self.assertTrue(Solver(t).solve()["ok"])
        t, _, er = normalize({"box": "row", "seq": True, "children": [{"el": "text", "text": "x", "style": "soft"}] * 3})
        res = Solver(t).solve()
        self.assertEqual(len(res["seq"][0]), 3)

    def test_top_row_not_stretched(self):
        from pptlab.solver import Solver
        from pptlab.spec import normalize
        t, _, _ = normalize({"box": "row", "children": [{"el": "text", "text": "短", "style": "soft"}] * 3})
        res = Solver(t).solve()
        self.assertLess(res["cards"][0][1][3], 500)


class EditTest(unittest.TestCase):
    """方式 B：在上传的 PPT 上改文字、补空白；没提到的部分不动"""

    @classmethod
    def setUpClass(cls):
        import tempfile, os
        from pptlab.render import render_deck_file
        cls.tmp = tempfile.mkdtemp()
        cls.src = os.path.join(cls.tmp, "src.pptx")
        here = os.path.dirname(os.path.abspath(__file__))
        from pptlab.tools.make_test_template import build
        build(cls.src)  # 中性的通用模板样例

    def test_inventory_and_edit(self):
        from pptlab import pptxio as X
        d = X.Doc(self.src)
        inv = X.inventory(d)
        self.assertGreater(len(inv), 3)
        before = {p: d.files[p] for p in d.files}
        # 找一页带文字的内容页，改第一个文本框
        rec = next(r for r in inv[2:] if any(s["kind"] == "text" and s.get("text") for s in r["shapes"]))
        s = next(s for s in rec["shapes"] if s["kind"] == "text" and s.get("text"))
        rep = X.apply_ops(d, [{"slide": rec["slide"], "shape": s["i"], "text": "改过的文字"}], inv)
        self.assertIn("改为", rep[0][1])
        d2 = X.Doc(d.save())
        inv2 = X.inventory(d2)
        self.assertEqual(next(x for x in inv2[rec["slide"] - 1]["shapes"] if x["i"] == s["i"])["text"], "改过的文字")
        changed = [p for p in before if d.files[p] != before[p]]
        self.assertEqual(changed, [rec["part"]])  # 只有这一页变了

    def test_fill_blank(self):
        from pptlab import pptxio as X
        d = X.Doc(self.src)
        inv = X.inventory(d)
        end = len(inv)  # 封底一般有空白
        rec = next((r for r in inv if r["blanks"] and r["blanks"][0]["box"][2] > 600 and r["blanks"][0]["box"][3] > 300), None)
        if rec is None:
            self.skipTest("样张里没有足够大的空白")
        n0 = len(rec["shapes"])
        rep = X.apply_ops(d, [{"slide": rec["slide"], "blank": 1, "page": {"type": "bullets", "title": "t",
                                                                       "items": ["第一条 30 天", "第二条", "第三条"]}}], inv)
        self.assertIn("补上内容", rep[0][1], rep)
        inv2 = X.inventory(X.Doc(d.save()))
        self.assertGreater(len(inv2[rec["slide"] - 1]["shapes"]), n0)
        self.assertGreater(end, 0)


class EnrichTest(unittest.TestCase):
    def test_compute(self):
        from pptlab import enrich as E
        t = [c["text"] for c in E.compute([{"name": "余额", "value": 86.4, "unit": "亿元", "last_year": 73.1, "target": 90},
                                           {"name": "不良率", "value": "0.62%", "prev": "0.70%"}])]
        self.assertIn("余额同比增长 18.2%（73.1 → 86.4亿元）", t)
        self.assertIn("余额完成目标的 96%，还差 3.6亿元", t)
        self.assertIn("不良率较上期下降 0.08 个百分点", t)

    def test_check_and_clean(self):
        from pptlab import enrich as E
        deck = {"pages": [{"type": "bullets", "title": "余额 86.4 亿元", "section": "总体情况",
                           "items": ["进一步加强管控，持续提升质量", "新签 37 家【需核实：家数】", "不良率下降【待补：降幅】", "同业 1.2%"]}]}
        r = E.check(deck, "余额 86.4 亿元", [], "report")
        kinds = [m for _, _, m in r["issues"]]
        self.assertTrue(any(m.startswith("空话") for m in kinds))
        self.assertTrue(any("1.2" in m for m in kinds))
        self.assertEqual(len(r["todo"]), 1)
        self.assertEqual(len(r["verify"]), 1)
        self.assertNotIn("总体情况", r["missing_sections"])
        c = E.clean(deck)
        self.assertNotIn("【", json.dumps(c, ensure_ascii=False))
        self.assertNotIn("section", c["pages"][0])


class ReuseTest(unittest.TestCase):
    """方式 A：拿一份现成 PPT 当模板重新生成"""

    def test_build_from_upload(self):
        import tempfile
        from pptlab.render import render_deck_file
        from pptlab import reuse as RU, pptxio as X
        tmp = tempfile.mkdtemp()
        here = os.path.dirname(os.path.abspath(__file__))
        src = os.path.join(tmp, "up.pptx")
        from pptlab.tools.make_test_template import build
        build(src)
        d = X.Doc(src)
        ana = RU.analyze(d)
        self.assertEqual(ana["cover"], 0)
        self.assertIsNotNone(ana["content"])
        self.assertIsNotNone(ana["end"])
        deck = json.load(open(os.path.join(EX, "sample-deck.json"), encoding="utf-8"))
        out = os.path.join(tmp, "out.pptx")
        data, rep = RU.build(src, deck, out)
        d2 = X.Doc(out)
        n = len(deck.get("pages") or [p for c in deck.get("chapters") for p in c["pages"]])
        self.assertGreaterEqual(len(d2.slides), n - 3)
        # 旧页都删掉了：包里的页面文件数 = 新页数
        self.assertEqual(len([p for p in d2.files if re.match(r"ppt/slides/slide\d+\.xml$", p)]), len(d2.slides))


class PickTest(unittest.TestCase):
    def test_recommend(self):
        from pptlab import pick
        self.assertEqual(len(pick.all_templates()), 72)
        r = pick.recommend("2027 年数字化转型规划：数据平台与科技创新")
        self.assertEqual(len(r), 3)
        self.assertEqual(len(set(x["cover"] for x in r)), 3)
        self.assertEqual(len(set(x["palette"] for x in r)), 3)
        self.assertEqual(r[0]["cover"], "mosaic")
