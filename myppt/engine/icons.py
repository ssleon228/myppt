"""图标库：209 个矢量图标（28 线性 + 181 Font Awesome Solid，OFL/CC-BY 许可），画成原生 custGeom 形状。

用法：
  icon 字段可写图标 id（如 "fa-coins"、"coins"、"money"）、emoji（"💰"），或留空。
  emoji / 留空 / 写错的 id → 按标题关键词自动选一个语义相近的图标（同一页内尽量不重复）。
"""
import json
import os
import re

from .ooxml.geom import Path, parse_svg_path, svg_elements_to_path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ICONS = None
_PATHS = {}


def icons():
    global _ICONS
    if _ICONS is None:
        with open(os.path.join(_HERE, "data", "icons.json"), encoding="utf-8") as f:
            _ICONS = json.load(f)
    return _ICONS


def icon_ids():
    return list(icons().keys())


# ── emoji → 图标 ──
EMOJI = {
    "💰": "fa-coins", "💵": "fa-money-bill-wave", "💴": "fa-money-bill-wave", "💸": "fa-money-bill-wave",
    "📈": "fa-arrow-trend-up", "📉": "fa-arrow-trend-down", "📊": "fa-chart-column", "👥": "fa-users",
    "👤": "person", "🎯": "fa-bullseye", "🛡": "fa-shield-halved", "🚗": "fa-car", "🚙": "fa-car", "⚙": "fa-gears",
    "💡": "fa-lightbulb", "🏦": "fa-landmark", "📱": "fa-mobile-screen", "🤝": "fa-handshake", "⏱": "fa-stopwatch",
    "⏰": "fa-clock", "🕒": "fa-clock", "🚀": "fa-rocket", "✅": "fa-circle-check", "✔": "fa-circle-check",
    "⚠": "fa-triangle-exclamation", "❗": "fa-circle-exclamation", "📋": "fa-clipboard-list", "🔒": "fa-lock",
    "🔐": "fa-lock", "🔑": "fa-key", "🌐": "fa-globe", "🌏": "fa-globe", "🌍": "fa-globe", "🏆": "fa-trophy",
    "🥇": "fa-medal", "⭐": "fa-star", "🌟": "fa-star", "📄": "fa-file-lines", "📑": "fa-file-lines",
    "📝": "fa-pen", "📅": "fa-calendar-days", "📆": "fa-calendar-days", "🔍": "fa-magnifying-glass",
    "🔎": "fa-magnifying-glass", "💳": "fa-credit-card", "🏢": "fa-building", "🏬": "fa-store", "🏪": "fa-shop",
    "🧠": "fa-brain", "🤖": "fa-robot", "🔄": "fa-arrows-rotate", "🔁": "fa-repeat", "🎁": "fa-gift",
    "❤": "fa-heart", "👍": "fa-thumbs-up", "📣": "fa-bullhorn", "📢": "fa-bullhorn", "💼": "fa-briefcase",
    "📦": "fa-box-open", "🚚": "fa-truck", "✈": "fa-plane", "🏠": "fa-house", "🏭": "fa-industry",
    "⚡": "fa-bolt", "🔥": "fa-fire", "🌱": "fa-seedling", "🍃": "fa-leaf", "♻": "fa-recycle", "📚": "fa-book",
    "🎓": "fa-graduation-cap", "🧩": "fa-puzzle-piece", "🧭": "fa-compass", "🗺": "fa-map", "📍": "fa-location-dot",
    "🔔": "fa-bell", "☎": "fa-phone", "📞": "fa-phone", "✉": "fa-envelope", "📧": "fa-envelope",
    "💬": "fa-comments", "🗂": "fa-folder-open", "📁": "fa-folder-open", "🧮": "fa-calculator", "⚖": "fa-scale-balanced",
    "💎": "fa-gem", "👑": "fa-crown", "🏁": "fa-flag-checkered", "🚩": "flag", "🧲": "fa-magnet", "🔧": "fa-screwdriver-wrench",
    "🛠": "fa-screwdriver-wrench", "💻": "fa-laptop-code", "🖥": "fa-server", "☁": "fa-cloud", "🏥": "fa-hospital",
    "🛒": "fa-cart-shopping", "🏷": "fa-tag", "🪙": "fa-coins", "🐷": "fa-piggy-bank", "👛": "fa-wallet",
    "📌": "fa-location-dot", "🔗": "fa-link", "⏳": "fa-hourglass-half", "📜": "fa-file-contract", "🧾": "fa-file-invoice-dollar",
}

# ── 业务关键词 → 图标（优先于标签匹配；越靠前越优先） ──
KEYWORDS = [
    ("车贷|汽车|车辆|购车|二手车|新能源车|车商|经销商|4S", "fa-car"),
    ("放款|投放|贷款|授信|信贷|融资", "fa-hand-holding-dollar"),
    ("利率|定价|费率|百分比|占比提升", "fa-percent"),
    ("营收|收入|利润|收益|中收|盈利", "fa-money-bill-trend-up"),
    ("资金|规模|余额|存款|资产", "fa-coins"),
    ("成本|节约|降本|储蓄", "fa-piggy-bank"),
    ("预算", "fa-wallet"),
    ("支付|结算|收单|信用卡|银行卡", "fa-credit-card"),
    ("不良|逾期|风险|预警|隐患|违约|欺诈", "fa-triangle-exclamation"),
    ("风控|合规|安全|防控|审查|内控|监管", "fa-shield-halved"),
    ("客户|客群|用户|会员", "fa-users"),
    ("团队|人员|队伍|人才|组织", "fa-people-group"),
    ("培训|赋能|学习|教育", "fa-graduation-cap"),
    ("合作|伙伴|协同|联动|签约|生态", "fa-handshake"),
    ("渠道|网点|门店|厂商", "fa-store"),
    ("线上|数字化|手机|移动|App|APP|小程序", "fa-mobile-screen"),
    ("系统|平台|科技|技术|IT", "fa-laptop-code"),
    ("数据|报表|统计|分析", "fa-chart-column"),
    ("智能|AI|模型|算法", "fa-brain"),
    ("自动|机器人", "fa-robot"),
    ("流程|机制|制度|管理|运营", "fa-gears"),
    ("效率|提速|时效|审批", "fa-stopwatch"),
    ("增长|提升|上升|突破|增速", "fa-arrow-trend-up"),
    ("下降|下滑|回落|减少", "fa-arrow-trend-down"),
    ("目标|聚焦|指标|任务", "fa-bullseye"),
    ("达成|完成|达标|通过", "fa-circle-check"),
    ("计划|安排|排期|节奏|时间|周期", "fa-calendar-days"),
    ("里程碑|节点|冲刺", "fa-flag-checkered"),
    ("创新|新产品|产品|方案", "fa-lightbulb"),
    ("营销|推广|宣传|活动|获客", "fa-bullhorn"),
    ("服务|体验|满意|关怀", "fa-heart"),
    ("市场|行业|区域|全国|全球", "fa-globe"),
    ("优势|亮点|标杆|领先", "fa-star"),
    ("荣誉|奖|冠军|第一", "fa-trophy"),
    ("问题|不足|短板|痛点", "fa-circle-exclamation"),
    ("调研|洞察|研究|搜索", "fa-magnifying-glass"),
    ("战略|方向|规划|路径", "fa-compass"),
    ("沟通|反馈|交流|会议", "fa-comments"),
    ("合同|协议|文件|报告|材料", "fa-file-lines"),
    ("考核|评价|评估|检查|验收", "fa-clipboard-check"),
    ("保障|支持|兜底|保险", "fa-umbrella"),
    ("启动|加速|上线|落地", "fa-rocket"),
    ("机构|分行|支行|银行|总行", "fa-landmark"),
]
_KW = [(re.compile(p), i) for p, i in KEYWORDS]
_GENERIC = ["fa-bullseye", "fa-lightbulb", "fa-star", "fa-gem", "fa-rocket", "fa-gears", "fa-chart-column",
            "fa-handshake", "fa-shield-halved", "fa-users"]


def _label_index():
    idx = []
    for iid, d in icons().items():
        for w in str(d.get("label") or "").split("/"):
            w = w.strip()
            if len(w) >= 2:
                idx.append((w, iid))
    idx.sort(key=lambda t: -len(t[0]))
    return idx


_LABELS = None


def _norm_id(name):
    if not name:
        return None
    n = str(name).strip()
    ic = icons()
    if n in ic:
        return n
    low = n.lower()
    if low in ic:
        return low
    if "fa-" + low in ic:
        return "fa-" + low
    if low.startswith("fa-") and low[3:] in ic:
        return low[3:]
    return None


def _emoji_id(s):
    s = str(s or "").replace("️", "").strip()
    if not s:
        return None
    if s in EMOJI:
        return EMOJI[s]
    for ch in s:
        if ch in EMOJI:
            return EMOJI[ch]
    return None


def auto_pick(text, used=None):
    """按文字语义选图标；used 为本页已用集合（尽量不重复）"""
    global _LABELS
    t = str(text or "")
    used = used if used is not None else set()
    cands = []
    for rx, iid in _KW:
        if rx.search(t):
            cands.append(iid)
    if _LABELS is None:
        _LABELS = _label_index()
    for w, iid in _LABELS:
        if w in t:
            cands.append(iid)
    for iid in cands:
        if iid not in used:
            return iid
    if cands:
        return cands[0]
    for iid in _GENERIC:
        if iid not in used:
            return iid
    return _GENERIC[0]


def resolve(icon, text=None, used=None, auto=True):
    """icon 字段 → 图标 id；无法解析且 auto=False 时返回 None"""
    iid = _norm_id(icon) or _emoji_id(icon)
    if iid:
        return iid
    if not auto:
        return None
    return auto_pick(text or (icon if isinstance(icon, str) else ""), used)


def icon_path(iid):
    """→ (Path, (ox, oy, w, h) viewBox, filled)"""
    if iid in _PATHS:
        return _PATHS[iid]
    d = icons().get(iid)
    if not d:
        return None
    vb = [float(v) for v in str(d.get("viewBox") or "0 0 24 24").split()]
    p = svg_elements_to_path(d.get("svg") or "")
    res = (p, tuple(vb), bool(d.get("filled")))
    _PATHS[iid] = res
    return res


def draw_icon_id(slide, iid, x, y, w, h, color):
    """在设计稿坐标框 (x,y,w,h) 内等比居中画图标；返回是否画成"""
    got = icon_path(iid)
    if not got:
        return False
    p, (ox, oy, vw, vh), filled = got
    if p.empty():
        return False
    s = min(w / vw, h / vh)
    dw, dh = vw * s, vh * s
    dx, dy = x + (w - dw) / 2, y + (h - dh) / 2
    o = dict(local=(ox, oy, vw, vh), x=dx / 144.0, y=dy / 144.0, w=dw / 144.0, h=dh / 144.0)
    if filled:
        slide.add_custom(p, fill={"color": color}, line={"type": "none"}, name="Icon " + iid, **o)
    else:
        # 线性图标：24 单位画布描边 2 → 线宽 = 2/24 × 绘制尺寸（px）→ pt = px/2
        lw = max(0.75, (2.0 / vw) * dw / 2.0)
        slide.add_custom(p, fill={"type": "none"}, line={"color": color, "width": lw, "cap": "rnd", "join": "round"},
                         name="Icon " + iid, **o)
    return True


def draw_icon(slide, name, x, y, w, h, color):
    iid = _norm_id(name) or _emoji_id(name)
    if not iid:
        return False
    return draw_icon_id(slide, iid, x, y, w, h, color)
