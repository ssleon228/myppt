"""最小 OOXML（PresentationML）写入器：只用标准库（zipfile + 字符串模板）。

坐标单位：调用方传英寸（与 pptxgenjs 同口径），内部换算 EMU。
"""
from .package import Presentation  # noqa: F401
