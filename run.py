"""myppt 统一入口（在任何目录都能调用）：
  python run.py make  deck.json 输出.pptx          用系统模板新做（不写 brand 就用推荐的第 1 套）
  python run.py pick  deck.json --preview 目录      推荐 3 套系统模板并出预览
  python run.py reuse analyze|build 上传.pptx ...   用用户的 PPT 当模板
  python run.py edit  inspect|apply 上传.pptx ...   在用户的 PPT 上修改
  python run.py enrich framework|compute|check ...  内容丰富与检查
  python run.py sample-template 输出.pptx           生成一份中性的示例模板（试路线一/路线二用）
  python run.py test                                自测
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MODS = {"make": "myppt", "pick": "myppt.pick", "reuse": "myppt.reuse", "edit": "myppt.edit",
        "enrich": "myppt.enrich", "sample-template": "myppt.tools.make_test_template"}


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = a[0], a[1:]
    if cmd == "test":
        import unittest
        suite = unittest.defaultTestLoader.loadTestsFromName("myppt.tests.test_lab")
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    if cmd not in MODS:
        if cmd.endswith(".json"):  # 直接给 deck.json：当作 make
            cmd, rest = "make", a
        else:
            print("不认识的命令：%s\n%s" % (cmd, __doc__))
            return 2
    sys.argv = [MODS[cmd]] + rest
    try:
        runpy.run_module(MODS[cmd], run_name="__main__", alter_sys=True)
    except SystemExit as e:
        return e.code or 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
