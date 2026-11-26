# pptlab

会自己设计的 PPT 生成技能（实验版）。纯 Python 标准库（3.8+），零第三方依赖，自带底层排版引擎。
本仓库根目录就是技能根目录：`SKILL.md`（技能说明和完整流程）、`run.py`（统一入口）、`pptlab/`（代码）。

```
python run.py make  deck.json 输出.pptx           # 用系统模板新做
python run.py pick  deck.json --preview 预览目录   # 推荐 3 套系统模板
python run.py reuse analyze|build 上传.pptx ...    # 用用户的 PPT 当模板
python run.py edit  inspect|apply 上传.pptx ...    # 在用户的 PPT 上修改
python run.py enrich framework|compute|check ...   # 内容丰富与检查
python run.py sample-template 示例模板.pptx        # 中性示例模板
python run.py test                                 # 自测
python tools/build_skill.py                        # 打包：完整包（含 Windows Python 和字体）+ 精简包
```

版面写法见 `pptlab/LAYOUT.md`，整套模板设计见 `pptlab/BRAND.md`。
