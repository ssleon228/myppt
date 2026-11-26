"""生成一份中性的「用户模板」样例 PPT，用来测试「用我的模板新做」和「在我的 PPT 上改」。

和真实世界里很多公司模板一样：母版是空的，Banner、标志、页脚直接画在每一页上；
有封面、目录、章节页、内容页（含「请输入…」提示框和留白）、封底。公司名是虚构的「示例公司」。
    python -m pptlab.tools.make_test_template 输出.pptx
"""
import os
import sys

from ..engine.ooxml.package import Presentation

INK, ACC, SOFT, GRAY = "2F3E46", "E07A3F", "F3F1EE", "8A8F93"
FONT = "微软雅黑"


def IN(px):
    return px / 144.0


def _logo(s, x, y, dark=True):
    s.add_shape("ellipse", x=IN(x), y=IN(y), w=IN(56), h=IN(56), fill={"color": ACC})
    s.add_text("示例公司  SAMPLE CO.", x=IN(x + 70), y=IN(y + 4), w=IN(520), h=IN(48), fontSize=16, bold=True,
               color=INK if dark else "FFFFFF", fontFace=FONT, valign="middle", name="Logo")


def _banner(s, title):
    s.add_shape("rect", x=0, y=0, w=IN(1920), h=IN(130), fill={"color": INK})
    s.add_shape("rect", x=0, y=IN(130), w=IN(1920), h=IN(8), fill={"color": ACC})
    s.add_text(title, x=IN(80), y=IN(25), w=IN(1400), h=IN(80), fontSize=26, bold=True, color="FFFFFF",
               fontFace=FONT, valign="middle", name="Title")
    s.add_shape("ellipse", x=IN(1780), y=IN(37), w=IN(56), h=IN(56), fill={"color": ACC})
    s.add_shape("line", x=IN(80), y=IN(1020), w=IN(1760), h=0, line={"color": "D9D6D2", "width": 1})
    s.add_text("示例公司 · 内部资料", x=IN(80), y=IN(1026), w=IN(600), h=IN(40), fontSize=10, color=GRAY, fontFace=FONT)


def build(out):
    theme = {"primary": INK, "mid": "3D5059", "blue": INK, "accent": ACC, "green": "6A9C78", "deep": "1F2A30",
             "text": "333333", "gray": GRAY, "line": "D9D6D2", "soft": SOFT}
    p = Presentation(13.333, 7.5, title="示例公司通用模板", theme_colors=theme, font=FONT, font_hei=FONT)
    p.autofit = False
    # 1 封面
    s = p.add_slide()
    s.add_shape("rect", x=0, y=0, w=IN(1920), h=IN(1080), fill={"color": SOFT})
    s.add_shape("rect", x=0, y=IN(330), w=IN(1920), h=IN(330), fill={"color": INK})
    s.add_shape("rect", x=IN(120), y=IN(660), w=IN(260), h=IN(10), fill={"color": ACC})
    _logo(s, 120, 90)
    s.add_text("请输入标题", x=IN(120), y=IN(400), w=IN(1500), h=IN(120), fontSize=44, bold=True, color="FFFFFF",
               fontFace=FONT, valign="middle", name="Title")
    s.add_text("请输入副标题", x=IN(120), y=IN(530), w=IN(1500), h=IN(70), fontSize=20, color="FFFFFF", fontFace=FONT,
               valign="middle")
    s.add_text("部门 | 日期", x=IN(120), y=IN(720), w=IN(800), h=IN(50), fontSize=14, color=GRAY, fontFace=FONT)
    # 2 目录
    s = p.add_slide()
    s.add_shape("rect", x=0, y=0, w=IN(620), h=IN(1080), fill={"color": INK})
    s.add_text([{"text": "目录", "options": {"breakLine": True}}, {"text": "CONTENTS", "options": {"fontSize": 16}}],
               x=IN(100), y=IN(420), w=IN(460), h=IN(200), fontSize=48, bold=True, color="FFFFFF", fontFace=FONT)
    for i in range(4):
        y = 230 + i * 170
        s.add_text("%02d" % (i + 1), x=IN(760), y=IN(y), w=IN(120), h=IN(90), fontSize=36, bold=True, color=ACC,
                   fontFace=FONT, valign="middle")
        s.add_text("请输入目录内容", x=IN(900), y=IN(y), w=IN(860), h=IN(90), fontSize=22, color=INK, fontFace=FONT,
                   valign="middle")
    # 3 章节页
    s = p.add_slide()
    s.add_shape("rect", x=0, y=0, w=IN(1920), h=IN(1080), fill={"color": INK})
    s.add_text("01", x=IN(160), y=IN(330), w=IN(400), h=IN(260), fontSize=120, bold=True, color=ACC, fontFace=FONT,
               valign="middle")
    s.add_text("请输入章节标题", x=IN(600), y=IN(400), w=IN(1200), h=IN(120), fontSize=40, bold=True, color="FFFFFF",
               fontFace=FONT, valign="middle")
    # 4 内容页：文字 + 留白
    s = p.add_slide()
    _banner(s, "年度重点工作回顾")
    s.add_text("一、门店网络持续扩张，全年净增门店 42 家。", x=IN(100), y=IN(200), w=IN(1700), h=IN(60), fontSize=18,
               color=INK, fontFace=FONT)
    s.add_text("二、会员体系完成升级，付费会员突破 10 万人。", x=IN(100), y=IN(270), w=IN(1700), h=IN(60), fontSize=18,
               color=INK, fontFace=FONT)
    # 5 内容页：三个「请输入」框
    s = p.add_slide()
    _banner(s, "核心指标")
    for i in range(3):
        x = 100 + i * 590
        s.add_shape("roundRect", x=IN(x), y=IN(220), w=IN(540), h=IN(300), fill={"color": SOFT})
        s.add_text("请输入数字", x=IN(x + 30), y=IN(260), w=IN(480), h=IN(110), fontSize=40, bold=True, color=ACC,
                   fontFace=FONT, align="center", valign="middle")
        s.add_text("请输入说明文字", x=IN(x + 30), y=IN(390), w=IN(480), h=IN(80), fontSize=16, color=GRAY,
                   fontFace=FONT, align="center", valign="middle")
    # 6 内容页：空白
    s = p.add_slide()
    _banner(s, "请输入标题")
    # 7 封底
    s = p.add_slide()
    s.add_shape("rect", x=0, y=0, w=IN(1920), h=IN(1080), fill={"color": INK})
    s.add_text("谢谢  THANK YOU", x=0, y=IN(440), w=IN(1920), h=IN(140), fontSize=48, bold=True, color="FFFFFF",
               fontFace=FONT, align="center", valign="middle")
    _logo(s, 800, 800, dark=False)
    data = p.to_bytes()
    d = os.path.dirname(os.path.abspath(out))
    os.makedirs(d, exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "示例公司通用模板.pptx"))
