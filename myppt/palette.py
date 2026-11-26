"""配色系统：精选色板 + 由一个主色推导整套配色，程序检查对比度。

AI 只能说「气质」（如 稳重金融、科技、政务）或给一个主色；具体每个颜色由程序定：
  · 有对应气质 → 用精选色板（人工调好的，主色/辅色/点缀色/深色/中性灰成套）
  · 只给主色 → 按色彩规则推导：饱和度和明度夹到「耐看」区间，辅色取邻近色，点缀色取暖色互补，灰色带一点主色调
  · 最后统一过对比度检查（白字压主色 ≥4.5、正文 ≥10、次要文字 ≥4.5），不达标自动加深
"""
import colorsys

# 精选色板：primary 主色 / secondary 辅色 / accent 点缀（少量用）/ dark 深色页
PALETTES = {
    "navy-gold":      dict(name="藏青金", mood="稳重 金融 银行 年报 正式", primary="17365D", secondary="2F6CB3", accent="C9A227", dark="0E2240"),
    "royal-blue":     dict(name="皇家蓝", mood="银行 国际 商务 专业", primary="0B4F9C", secondary="2E86DE", accent="F5A623", dark="062A55"),
    "teal-coral":     dict(name="青珊瑚", mood="现代 清新 零售 服务 年轻", primary="0F7C80", secondary="3BA7A0", accent="E9724C", dark="0B3D44"),
    "ink-red":        dict(name="中国红", mood="政务 党建 国企 庆典 红色", primary="A51C24", secondary="C8463D", accent="D9A441", dark="5A0E12"),
    "graphite-amber": dict(name="石墨橙", mood="工业 制造 工程 硬朗", primary="2B2F36", secondary="4A5563", accent="F2994A", dark="16181C"),
    "indigo-cyan":    dict(name="靛青", mood="科技 数字化 互联网 AI 创新", primary="33358A", secondary="5B5FC7", accent="22B8CF", dark="1B1C4A"),
    "forest":         dict(name="森林绿", mood="绿色 环保 ESG 农业 可持续", primary="2D6A4F", secondary="52B788", accent="E9C46A", dark="1B4332"),
    "burgundy-sand":  dict(name="酒红沙", mood="高端 奢华 私行 财富 品牌", primary="6D213C", secondary="946E83", accent="C5A880", dark="3B0F20"),
    "sky-mint":       dict(name="天青薄荷", mood="医疗 健康 教育 公益", primary="1E6FA8", secondary="4FB3BF", accent="7BC67E", dark="123E5E"),
    "charcoal-teal":  dict(name="炭灰青", mood="咨询 分析 研究 报告 简约", primary="263238", secondary="00897B", accent="FFB300", dark="101619"),
    "plum-orange":    dict(name="梅紫橙", mood="营销 活力 创意 活动 推介", primary="5B2A86", secondary="9B4DCA", accent="FF8C42", dark="2E1446"),
    "slate-sky":      dict(name="岩灰天蓝", mood="极简 产品 发布 方案", primary="334155", secondary="0EA5E9", accent="F43F5E", dark="0F172A"),
}


# ── 颜色数学 ──────────────────────────────────────────

def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _hex(rgb):
    return "".join("%02X" % int(round(max(0, min(1, c)) * 255)) for c in rgb)


def hsl(h):
    r, g, b = _rgb(h)
    hh, l, s = colorsys.rgb_to_hls(r, g, b)
    return hh * 360, s, l


def from_hsl(hh, s, l):
    return _hex(colorsys.hls_to_rgb((hh % 360) / 360.0, max(0, min(1, l)), max(0, min(1, s))))


def luminance(h):
    def ch(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def darken_until(c, bg, need, step=0.03):
    """把 c 加深（降明度）直到与 bg 对比度 ≥ need"""
    hh, s, l = hsl(c)
    while contrast(c, bg) < need and l > 0.05:
        l -= step
        c = from_hsl(hh, s, l)
    return c


# ── 推导 ────────────────────────────────────────────

def derive(seed):
    """由一个主色推导 primary/secondary/accent/dark"""
    hh, s, l = hsl(seed)
    if s < 0.08:  # 近似灰：当石墨色处理，点缀用暖橙
        return dict(primary=from_hsl(hh, 0.08, min(0.3, l)), secondary=from_hsl(210, 0.12, 0.42),
                    accent="F2994A", dark=from_hsl(hh, 0.08, 0.1))
    s = max(0.38, min(0.78, s))
    l = max(0.26, min(0.44, l))
    primary = from_hsl(hh, s, l)
    secondary = from_hsl(hh + 14, s * 0.85, min(0.58, l + 0.16))
    # 点缀色：冷色主色配暖金/珊瑚，暖色主色配青/金
    if 180 <= hh <= 300:
        accent = "E0A526" if hh < 240 else "F08A4B"
    elif hh < 40 or hh > 330:
        accent = "D9A441"
    else:
        accent = "E9724C"
    dark = from_hsl(hh, s * 0.7, 0.13)
    return dict(primary=primary, secondary=secondary, accent=accent, dark=dark)


def pick_by_mood(text):
    """气质关键词 → 精选色板 id（关键词命中最多的那套；都不中返回 None）"""
    t = str(text or "")
    best, hits = None, 0
    for pid, p in PALETTES.items():
        n = sum(1 for w in p["mood"].split() if w and w in t)
        if pid in t or p["name"] in t:
            n += 5
        if n > hits:
            best, hits = pid, n
    return best


def build(spec=None):
    """spec: {palette: 色板id, mood: 气质文字, primary: 主色hex} → 完整角色色板（已过对比度检查）
    返回 (pal, notes)。"""
    spec = spec or {}
    notes = []
    base = None
    pid = spec.get("palette")
    if pid and pid not in PALETTES:
        notes.append("色板 %r 不存在，改按气质/主色挑" % pid)
        pid = None
    if not pid and spec.get("primary"):
        try:
            base = derive(str(spec["primary"]).lstrip("#")[:6])
            notes.append("按主色 #%s 推导整套配色" % str(spec["primary"]).lstrip("#")[:6].upper())
        except ValueError:
            notes.append("主色 %r 不是有效颜色，忽略" % spec["primary"])
    if base is None:
        pid = pid or pick_by_mood(spec.get("mood")) or "royal-blue"
        base = dict(PALETTES[pid])
        notes.append("色板：%s（%s）" % (PALETTES[pid]["name"], pid))
    P = base["primary"]
    hh, s, _ = hsl(P)
    pal = {
        "primary": P, "secondary": base["secondary"], "accent": base["accent"], "dark": base["dark"],
        "ink": from_hsl(hh, min(s, 0.18), 0.16),
        "muted": from_hsl(hh, min(s, 0.1), 0.42),
        "line": from_hsl(hh, min(s, 0.14), 0.87),
        "soft": from_hsl(hh, min(s, 0.45), 0.955),
        "soft2": from_hsl(hh, min(s, 0.12), 0.97),
        "white": "FFFFFF", "good": "2E9E6A", "warn": "C8553D",
    }
    # 对比度把关
    fixes = []
    for key, bg, need in (("primary", "FFFFFF", 4.5), ("dark", "FFFFFF", 10), ("ink", "FFFFFF", 12),
                          ("muted", "FFFFFF", 4.6)):
        before = pal[key]
        pal[key] = darken_until(pal[key], bg, need)
        if pal[key] != before:
            fixes.append(key)
    # 辅色/点缀色用作文字时的安全版本（作底色或装饰时用原色）
    pal["secondary_text"] = darken_until(pal["secondary"], "FFFFFF", 3.2)
    pal["accent_text"] = darken_until(pal["accent"], "FFFFFF", 3.0)
    pal["on_accent"] = "FFFFFF" if contrast("FFFFFF", pal["accent"]) >= 3 else pal["ink"]
    if fixes:
        notes.append("对比度不足已自动加深：%s" % "、".join(fixes))
    pal["chart"] = [pal["primary"], pal["secondary"], pal["accent"], mix(pal["primary"], "FFFFFF", 0.5), pal["muted"]]
    return pal, notes


def to_engine_colors(pal):
    """角色色板 → 底层引擎 模板 colors 键（让交给 底层引擎 画的页也用新配色）"""
    return {"primary": pal["primary"], "mid": pal["secondary"], "blue": pal["secondary_text"],
            "accent": pal["secondary"], "green": pal["accent"], "deep": pal["dark"], "text": pal["ink"],
            "gray": pal["muted"], "line": pal["line"], "soft": pal["soft2"]}
