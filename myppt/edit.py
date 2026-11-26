"""在用户上传的 PPT 上改内容、补空白。

  python -m myppt.edit inspect in.pptx [--json]          列出每页元素、可填空位、空白区域
  python -m myppt.edit apply in.pptx ops.json out.pptx   按 ops 修改，打印改动清单

ops.json 是一个列表，每条一种操作：
  {"slide": 3, "shape": 5, "text": "新文字（换行用 \\n）"}            改文本框（shape 用清单里的 [序号]）
  {"slide": 3, "shape": 12, "cell": [2, 3], "text": "1,280"}       改表格第 2 行第 3 列
  {"slide": 7, "blank": 1, "page": {页面 JSON，同 deck 的内容页}}     在第 1 块空白区域里排版
  {"slide": 7, "region": [x, y, w, h], "layout": {版面积木}}        在指定区域里排版（1920 宽的设计单位）
"""
import json
import sys

from . import pptxio as X


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 2 and a[0] == "inspect":
        d = X.Doc(a[1])
        inv = X.inventory(d)
        if "--json" in a:
            for r in inv:
                r.pop("part", None)
            print(json.dumps(inv, ensure_ascii=False, indent=1))
        else:
            print(X.describe(inv))
        return 0
    if len(a) >= 4 and a[0] == "apply":
        d = X.Doc(a[1])
        ops = json.load(open(a[2], encoding="utf-8"))
        rep = X.apply_ops(d, ops)
        d.save(a[3])
        for sn, msg in rep:
            print("第 %d 页：%s" % (sn, msg))
        print("已保存 %s（没提到的页面和元素保持原样）" % a[3])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
