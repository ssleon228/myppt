"""设计档位（design tokens）：AI 和程序只能从这些固定档位里挑，不能写任意字号/颜色/坐标。

坐标单位沿用 底层引擎：设计稿 1920×1080 px，导出 pt = px / 2。
"""

# 内容区（模板 Banner 以下、页脚以上）
PAGE_W, PAGE_H = 1920, 1080
AREA = dict(x=96, y=196, w=1728, h=800)

# 字号：每个角色一个基准字号，整页统一按「档位」等比放大或缩小（字少就放大填满，字多就缩小）
ROLE_BASE = {"display": 104, "h1": 56, "h2": 38, "lead": 32, "body": 28, "small": 23}
ROLE_MIN = {"display": 56, "h1": 40, "h2": 30, "lead": 26, "body": 24, "small": 21}
ROLE_MAX = {"display": 168, "h1": 72, "h2": 50, "lead": 44, "body": 36, "small": 27}
LEVELS = [0.86, 0.93, 1.0, 1.08, 1.16, 1.25, 1.36]  # 档位 0..6，2 = 基准
BASE_LEVEL = 2

ROLES = tuple(ROLE_BASE)
LINE_H = {"display": 1.0, "h1": 1.15, "h2": 1.2, "lead": 1.3, "body": 1.35, "small": 1.3}

# 间距三档
GAP = {"s": 16, "m": 32, "l": 56}
PAD = {"s": 20, "m": 32, "l": 44}

# 卡片样式
STYLES = ("none", "soft", "outline", "accent", "dark", "topbar", "leftbar", "panel", "panel-light",
          "raised", "rule", "block", "fine", "bracket")
# 颜色只能用角色名
COLOR_ROLES = ("ink", "muted", "primary", "accent", "white", "good", "warn", "dark")


def size(role, level):
    """角色 + 档位 → 字号（px，取偶数，保证 pt 为整数）"""
    v = ROLE_BASE[role] * LEVELS[max(0, min(len(LEVELS) - 1, level))]
    v = max(ROLE_MIN[role], min(ROLE_MAX[role], v))
    return int(round(v / 2.0)) * 2


def palette(C):
    """模板配色 → 角色色板"""
    from .engine.ooxml.util import mix
    primary = C.get("primary") or "2563EB"
    accent = C.get("blue") or C.get("accent") or primary
    dark = C.get("deep") or "002060"
    return {
        "primary": primary, "accent": accent, "dark": dark,
        "ink": C.get("text") or "424242", "muted": C.get("gray") or "797979",
        "line": C.get("line") or "DBDCDC", "soft": mix(primary, "FFFFFF", 0.92),
        "soft2": C.get("soft") or "F4F5F5", "white": "FFFFFF",
        "good": C.get("green") or "34D399", "warn": "C8553D",
    }
