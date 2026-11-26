"""自由路径（custGeom）：路径构建器 + SVG path 解析。

DrawingML 的 arcTo 以「当前点」为弧起点，参数是半径与起始角/扫过角（单位 1/60000 度，
0°=正东，顺时针，与屏幕坐标一致）。这里统一用局部坐标（任意单位）记录，输出时按缩放比换算成 EMU。
"""
import math
import re

from .util import fnum


class Path:
    def __init__(self):
        self.ops = []  # (kind, args)
        self._cur = (0.0, 0.0)
        self._start = (0.0, 0.0)

    # ── 基本命令 ──
    def move(self, x, y):
        self.ops.append(("M", (x, y)))
        self._cur = self._start = (x, y)
        return self

    def line(self, x, y):
        self.ops.append(("L", (x, y)))
        self._cur = (x, y)
        return self

    def cubic(self, x1, y1, x2, y2, x, y):
        self.ops.append(("C", (x1, y1, x2, y2, x, y)))
        self._cur = (x, y)
        return self

    def quad(self, x1, y1, x, y):
        self.ops.append(("Q", (x1, y1, x, y)))
        self._cur = (x, y)
        return self

    def arc(self, cx, cy, rx, ry, a0, a1, connect=True):
        """中心参数弧：从角 a0 到 a1（度，顺时针为正）。connect=True 时用直线连到弧起点"""
        sx = cx + rx * math.cos(math.radians(a0))
        sy = cy + ry * math.sin(math.radians(a0))
        if not self.ops:
            self.move(sx, sy)
        elif connect:
            if abs(self._cur[0] - sx) > 1e-6 or abs(self._cur[1] - sy) > 1e-6:
                self.line(sx, sy)
        else:
            self.move(sx, sy)
        self.ops.append(("A", (rx, ry, a0, a1 - a0)))
        self._cur = (cx + rx * math.cos(math.radians(a1)), cy + ry * math.sin(math.radians(a1)))
        return self

    def close(self):
        self.ops.append(("Z", ()))
        self._cur = self._start
        return self

    def polygon(self, pts):
        for i, (x, y) in enumerate(pts):
            (self.move if i == 0 else self.line)(x, y)
        return self.close()

    def empty(self):
        return not self.ops

    # ── 输出 ──
    def bbox(self):
        xs, ys = [], []
        cur = (0.0, 0.0)
        for k, a in self.ops:
            if k in ("M", "L"):
                xs.append(a[0]); ys.append(a[1]); cur = a
            elif k == "C":
                xs += [a[0], a[2], a[4]]; ys += [a[1], a[3], a[5]]; cur = (a[4], a[5])
            elif k == "Q":
                xs += [a[0], a[2]]; ys += [a[1], a[3]]; cur = (a[2], a[3])
            elif k == "A":
                rx, ry, st, sw = a
                cx = cur[0] - rx * math.cos(math.radians(st))
                cy = cur[1] - ry * math.sin(math.radians(st))
                n = max(2, int(abs(sw) / 10) + 2)
                for i in range(n + 1):
                    t = math.radians(st + sw * i / n)
                    xs.append(cx + rx * math.cos(t)); ys.append(cy + ry * math.sin(t))
                cur = (xs[-1], ys[-1])
        if not xs:
            return 0, 0, 0, 0
        return min(xs), min(ys), max(xs), max(ys)

    def to_custgeom(self, sx, sy, w_emu, h_emu, fill=True, stroke=True, ox=0.0, oy=0.0):
        """sx/sy：局部单位 → EMU 的缩放；ox/oy：局部坐标原点偏移（先减去）"""
        def X(v):
            return int(round((v - ox) * sx))

        def Y(v):
            return int(round((v - oy) * sy))

        out = []
        for k, a in self.ops:
            if k == "M":
                out.append('<a:moveTo><a:pt x="%d" y="%d"/></a:moveTo>' % (X(a[0]), Y(a[1])))
            elif k == "L":
                out.append('<a:lnTo><a:pt x="%d" y="%d"/></a:lnTo>' % (X(a[0]), Y(a[1])))
            elif k == "C":
                out.append('<a:cubicBezTo><a:pt x="%d" y="%d"/><a:pt x="%d" y="%d"/><a:pt x="%d" y="%d"/></a:cubicBezTo>'
                           % (X(a[0]), Y(a[1]), X(a[2]), Y(a[3]), X(a[4]), Y(a[5])))
            elif k == "Q":
                out.append('<a:quadBezTo><a:pt x="%d" y="%d"/><a:pt x="%d" y="%d"/></a:quadBezTo>'
                           % (X(a[0]), Y(a[1]), X(a[2]), Y(a[3])))
            elif k == "A":
                rx, ry, st, sw = a
                out.append('<a:arcTo wR="%d" hR="%d" stAng="%d" swAng="%d"/>'
                           % (int(round(abs(rx * sx))), int(round(abs(ry * sy))), int(round(st * 60000)), int(round(sw * 60000))))
            elif k == "Z":
                out.append("<a:close/>")
        attrs = ' w="%d" h="%d"' % (max(1, int(w_emu)), max(1, int(h_emu)))
        if not fill:
            attrs += ' fill="none"'
        if not stroke:
            attrs += ' stroke="0"'
        return ('<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/>'
                '<a:pathLst><a:path%s>%s</a:path></a:pathLst></a:custGeom>' % (attrs, "".join(out)))


# ── SVG path 解析 ─────────────────────────────────────────────

_TOK = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_svg_path(d, path=None, tx=0.0, ty=0.0, scale=1.0):
    """SVG path d → Path（支持全部命令含相对坐标与椭圆弧；不支持 x 轴旋转的椭圆弧近似为无旋转）"""
    p = path or Path()
    toks = _TOK.findall(d or "")
    i = 0
    cmd = None
    cx = cy = 0.0
    sx0 = sy0 = 0.0
    last_ctrl = None
    last_cmd = None

    def T(x, y):
        return (x * scale + tx, y * scale + ty)

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    def has_num():
        return i < len(toks) and not toks[i].isalpha()

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
        elif cmd is None:
            i += 1
            continue
        c = cmd
        rel = c.islower()
        C = c.upper()
        if C == "Z":
            p.close()
            cx, cy = sx0, sy0
            last_ctrl = None
            last_cmd = "Z"
            continue
        if not has_num():
            continue
        try:
            if C == "M":
                x, y = num(), num()
                if rel:
                    x += cx; y += cy
                p.move(*T(x, y))
                cx, cy = sx0, sy0 = x, y
                cmd = "l" if rel else "L"
                last_ctrl = None
            elif C == "L":
                x, y = num(), num()
                if rel:
                    x += cx; y += cy
                p.line(*T(x, y)); cx, cy = x, y; last_ctrl = None
            elif C == "H":
                x = num()
                if rel:
                    x += cx
                p.line(*T(x, cy)); cx = x; last_ctrl = None
            elif C == "V":
                y = num()
                if rel:
                    y += cy
                p.line(*T(cx, y)); cy = y; last_ctrl = None
            elif C in ("C", "S"):
                if C == "C":
                    x1, y1 = num(), num()
                    if rel:
                        x1 += cx; y1 += cy
                else:
                    if last_ctrl and last_cmd in ("C", "S"):
                        x1, y1 = 2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1]
                    else:
                        x1, y1 = cx, cy
                x2, y2, x, y = num(), num(), num(), num()
                if rel:
                    x2 += cx; y2 += cy; x += cx; y += cy
                p.cubic(*(T(x1, y1) + T(x2, y2) + T(x, y)))
                last_ctrl = (x2, y2); cx, cy = x, y
            elif C in ("Q", "T"):
                if C == "Q":
                    x1, y1 = num(), num()
                    if rel:
                        x1 += cx; y1 += cy
                else:
                    if last_ctrl and last_cmd in ("Q", "T"):
                        x1, y1 = 2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1]
                    else:
                        x1, y1 = cx, cy
                x, y = num(), num()
                if rel:
                    x += cx; y += cy
                p.quad(*(T(x1, y1) + T(x, y)))
                last_ctrl = (x1, y1); cx, cy = x, y
            elif C == "A":
                rx, ry, _rot, large, sweep, x, y = num(), num(), num(), num(), num(), num(), num()
                if rel:
                    x += cx; y += cy
                _svg_arc(p, cx, cy, rx, ry, bool(large), bool(sweep), x, y, T, scale)
                cx, cy = x, y
                last_ctrl = None
        except (IndexError, ValueError):
            break
        last_cmd = C
    return p


def _svg_arc(p, x1, y1, rx, ry, large, sweep, x2, y2, T, scale):
    """SVG 端点弧 → 中心参数弧（无 x 轴旋转）"""
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        p.line(*T(x2, y2))
        return
    rx, ry = abs(rx), abs(ry)
    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    lam = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    num_ = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    co = math.sqrt(max(0.0, num_ / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp = co * rx * dy / ry
    cyp = -co * ry * dx / rx
    cx = cxp + (x1 + x2) / 2.0
    cy = cyp + (y1 + y2) / 2.0

    def ang(ux, uy):
        return math.degrees(math.atan2(uy, ux))

    a0 = ang((dx - cxp) / rx, (dy - cyp) / ry)
    a1 = ang((-dx - cxp) / rx, (-dy - cyp) / ry)
    sw = a1 - a0
    if sweep and sw < 0:
        sw += 360
    elif not sweep and sw > 0:
        sw -= 360
    ccx, ccy = T(cx, cy)
    p.arc(ccx, ccy, rx * scale, ry * scale, a0, a0 + sw)


# ── 简单 SVG 元素（图标用）→ Path ───────────────────────────────

_ELEM = re.compile(r"<(path|circle|ellipse|rect|line|polyline|polygon)\b([^>]*)/?>", re.I)
_ATTR = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


def svg_elements_to_path(markup, scale=1.0, tx=0.0, ty=0.0):
    p = Path()
    for m in _ELEM.finditer(markup or ""):
        tag = m.group(1).lower()
        at = dict(_ATTR.findall(m.group(2)))

        def f(k, d=0.0):
            try:
                return float(at.get(k, d))
            except ValueError:
                return d

        if tag == "path":
            parse_svg_path(at.get("d", ""), p, tx, ty, scale)
        elif tag in ("circle", "ellipse"):
            cx, cy = f("cx"), f("cy")
            rx = f("r") if tag == "circle" else f("rx")
            ry = f("r") if tag == "circle" else f("ry")
            p.arc(cx * scale + tx, cy * scale + ty, rx * scale, ry * scale, 0, 360, connect=False)
            p.close()
        elif tag == "rect":
            x, y, w, h = f("x"), f("y"), f("width"), f("height")
            r = f("rx", f("ry", 0))
            S = lambda a, b: (a * scale + tx, b * scale + ty)  # noqa: E731
            if r > 0:
                r = min(r, w / 2, h / 2)
                p.move(*S(x + r, y)).line(*S(x + w - r, y))
                p.arc(*(S(x + w - r, y + r) + (r * scale, r * scale, -90, 0)))
                p.line(*S(x + w, y + h - r))
                p.arc(*(S(x + w - r, y + h - r) + (r * scale, r * scale, 0, 90)))
                p.line(*S(x + r, y + h))
                p.arc(*(S(x + r, y + h - r) + (r * scale, r * scale, 90, 180)))
                p.line(*S(x, y + r))
                p.arc(*(S(x + r, y + r) + (r * scale, r * scale, 180, 270)))
                p.close()
            else:
                p.polygon([S(x, y), S(x + w, y), S(x + w, y + h), S(x, y + h)])
        elif tag == "line":
            p.move(f("x1") * scale + tx, f("y1") * scale + ty).line(f("x2") * scale + tx, f("y2") * scale + ty)
        elif tag in ("polyline", "polygon"):
            nums = [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)", at.get("points", ""))]
            pts = [(nums[i] * scale + tx, nums[i + 1] * scale + ty) for i in range(0, len(nums) - 1, 2)]
            for i, pt in enumerate(pts):
                (p.move if i == 0 else p.line)(*pt)
            if tag == "polygon" and pts:
                p.close()
    return p


def fmt(v):
    return fnum(v)
