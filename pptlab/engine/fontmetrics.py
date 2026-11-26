"""真实字宽：直接解析本机字体文件（TTF/OTF/TTC）的 cmap + hmtx 表，纯标准库。

为什么：估算（中文 1em / 西文 0.56em）对数字、字母、标点偏差可达 ±20%，导致溢出或留白过多。
PowerPoint 按字体真实字宽换行，这里读同一份字体文件，排版和成品一致。
找不到字体（或 PPT_REAL_METRICS=off）时回退估算，与 TS 版行为一致。

字体查找顺序：环境变量 PPTLAB_FONT_DIRS → 包内 / SKILL 内 fonts 目录 → 系统字体目录。
"""
import os
import re
import struct
import sys
import threading

CJK = re.compile("[\u2e80-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef、。，；：！？“”‘’（）《》【】]")


def estimate_em(ch):
    return 1.0 if CJK.match(ch) else 0.56


def is_cjk(ch):
    return bool(CJK.match(ch))


# ── 字体文件解析 ──────────────────────────────────────────────

class _FileView:
    """按需读字体文件：只读目录、name 表和用到的度量表，不把整个（中文字体常有十几 MB）文件读进内存"""

    def __init__(self, path):
        self.path = path
        self._chunks = []  # (start, bytes)
        self.preload(0, 4096)

    def preload(self, start, length):
        for s0, b in self._chunks:
            if s0 <= start and start + length <= s0 + len(b):
                return
        with open(self.path, "rb") as f:
            f.seek(start)
            self._chunks.append((start, f.read(length)))

    def __getitem__(self, sl):
        a, b = sl.start or 0, sl.stop
        for s0, buf in self._chunks:
            if s0 <= a and b <= s0 + len(buf):
                return buf[a - s0:b - s0]
        with open(self.path, "rb") as f:
            f.seek(a)
            buf = f.read(max(b - a, 4096))
        self._chunks.append((a, buf))
        return buf[:b - a]


class FontFile:
    """单个字体（TTC 中的一个 face）：只读 name/head/hhea/hmtx/cmap"""

    def __init__(self, path, data, offset=0):
        self.path = path
        self._data = data
        self.tables = {}
        num = struct.unpack(">H", data[offset + 4:offset + 6])[0]
        if isinstance(data, _FileView):
            data.preload(offset, 12 + 16 * num)
        for i in range(num):
            rec = offset + 12 + 16 * i
            tag = data[rec:rec + 4].decode("latin-1")
            off, length = struct.unpack(">II", data[rec + 8:rec + 16])
            self.tables[tag] = (off, length)
        if isinstance(data, _FileView):
            for tag in ("name", "head", "OS/2"):
                if tag in self.tables:
                    data.preload(*self.tables[tag])
        self.names = self._read_names()
        self._cmap = None
        self._adv = None
        self.upem = 1000
        if "head" in self.tables:
            o = self.tables["head"][0]
            self.upem = struct.unpack(">H", data[o + 18:o + 20])[0] or 1000
        self.bold = False
        if "OS/2" in self.tables:
            o = self.tables["OS/2"][0]
            weight = struct.unpack(">H", data[o + 4:o + 6])[0]
            sel = struct.unpack(">H", data[o + 62:o + 64])[0] if self.tables["OS/2"][1] >= 64 else 0
            self.bold = weight >= 600 or bool(sel & 0x20)
            self.weight = weight
        else:
            self.weight = 400

    def _read_names(self):
        out = set()
        if "name" not in self.tables:
            return out
        d = self._data
        o, _ = self.tables["name"]
        count, str_off = struct.unpack(">HH", d[o + 2:o + 6])
        for i in range(count):
            r = o + 6 + 12 * i
            pid, eid, lid, nid, length, off = struct.unpack(">HHHHHH", d[r:r + 12])
            if nid not in (1, 4, 16):
                continue
            raw = d[o + str_off + off:o + str_off + off + length]
            try:
                if pid == 3 or pid == 0:
                    s = raw.decode("utf-16-be")
                elif pid == 1 and eid == 0:
                    s = raw.decode("mac_roman")
                else:
                    continue
            except UnicodeDecodeError:
                continue
            s = s.strip()
            if s:
                out.add(s.lower())
        return out

    def _load(self):
        d = self._data
        if isinstance(d, _FileView):
            for tag in ("hhea", "hmtx", "cmap"):
                if tag in self.tables:
                    d.preload(*self.tables[tag])
        # hmtx
        hh = self.tables.get("hhea")
        hm = self.tables.get("hmtx")
        if not hh or not hm:
            self._adv = []
        else:
            n = struct.unpack(">H", d[hh[0] + 34:hh[0] + 36])[0]
            self._adv = list(struct.unpack(">%dH" % (2 * n), d[hm[0]:hm[0] + 4 * n])[0::2])
        # cmap
        cm = {}
        t = self.tables.get("cmap")
        if t:
            base = t[0]
            n = struct.unpack(">H", d[base + 2:base + 4])[0]
            subs = []
            for i in range(n):
                pid, eid, off = struct.unpack(">HHI", d[base + 4 + 8 * i:base + 12 + 8 * i])
                subs.append((pid, eid, base + off))
            # 偏好 format 12（全 Unicode），否则 format 4
            chosen = None
            for pid, eid, off in subs:
                fmt = struct.unpack(">H", d[off:off + 2])[0]
                if fmt == 12 and (pid, eid) in ((3, 10), (0, 4), (0, 6)):
                    chosen = (fmt, off)
                    break
            if not chosen:
                for pid, eid, off in subs:
                    fmt = struct.unpack(">H", d[off:off + 2])[0]
                    if fmt == 4 and (pid, eid) in ((3, 1), (0, 3), (0, 1), (0, 0)):
                        chosen = (fmt, off)
                        break
            if chosen:
                fmt, off = chosen
                if fmt == 4:
                    seg2 = struct.unpack(">H", d[off + 6:off + 8])[0]
                    segs = seg2 // 2
                    ends = struct.unpack(">%dH" % segs, d[off + 14:off + 14 + seg2])
                    starts = struct.unpack(">%dH" % segs, d[off + 16 + seg2:off + 16 + 2 * seg2])
                    deltas = struct.unpack(">%dh" % segs, d[off + 16 + 2 * seg2:off + 16 + 3 * seg2])
                    ro_base = off + 16 + 3 * seg2
                    ranges = struct.unpack(">%dH" % segs, d[ro_base:ro_base + seg2])
                    self._cmap = ("4", starts, ends, deltas, ranges, ro_base)
                else:
                    ngroups = struct.unpack(">I", d[off + 12:off + 16])[0]
                    groups = [struct.unpack(">III", d[off + 16 + 12 * i:off + 28 + 12 * i]) for i in range(ngroups)]
                    self._cmap = ("12", groups)
        if self._cmap is None:
            self._cmap = ("none",)
        self._cache = cm

    def glyph(self, cp):
        if self._adv is None:
            self._load()
        c = self._cmap
        d = self._data
        if c[0] == "4":
            if cp > 0xFFFF:
                return 0
            _, starts, ends, deltas, ranges, ro_base = c
            lo, hi = 0, len(ends) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if ends[mid] < cp:
                    lo = mid + 1
                else:
                    hi = mid
            i = lo
            if i >= len(ends) or starts[i] > cp or ends[i] < cp:
                return 0
            if ranges[i] == 0:
                return (cp + deltas[i]) & 0xFFFF
            addr = ro_base + 2 * i + ranges[i] + 2 * (cp - starts[i])
            g = struct.unpack(">H", d[addr:addr + 2])[0]
            return (g + deltas[i]) & 0xFFFF if g else 0
        if c[0] == "12":
            groups = c[1]
            lo, hi = 0, len(groups) - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                s, e, g = groups[mid]
                if cp < s:
                    hi = mid - 1
                elif cp > e:
                    lo = mid + 1
                else:
                    return g + cp - s
        return 0

    def advance_em(self, ch):
        """单字符前进宽度（em）；缺字返回 None"""
        g = self.glyph(ord(ch))
        if not g:
            return None
        adv = self._adv
        if not adv:
            return None
        w = adv[g] if g < len(adv) else adv[-1]
        return w / float(self.upem)


def _open_faces(path):
    try:
        data = _FileView(path)
    except OSError:
        return []
    faces = []
    try:
        if data[:4] == b"ttcf":
            n = struct.unpack(">I", data[8:12])[0]
            for i in range(n):
                off = struct.unpack(">I", data[12 + 4 * i:16 + 4 * i])[0]
                faces.append(FontFile(path, data, off))
        elif data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            faces.append(FontFile(path, data, 0))
    except (struct.error, IndexError, UnicodeDecodeError, OSError):
        return faces
    return faces


# ── 字体查找 ─────────────────────────────────────────────────

# 常见中文字体名 → 文件名关键字（加速命中；找不到再全量扫描）
ALIASES = {
    "微软雅黑": ["msyh", "microsoft yahei"],
    "microsoft yahei": ["msyh"],
    "黑体": ["simhei"],
    "simhei": ["simhei"],
    "宋体": ["simsun"],
    "思源黑体": ["sourcehansans", "source han sans", "notosanscjk", "noto sans cjk", "思源黑体"],
    "source han sans sc": ["sourcehansans", "notosanscjk"],
    "noto sans cjk sc": ["notosanscjk", "sourcehansans"],
    "montserrat": ["montserrat"],
    "苹方": ["pingfang"],
}
# 名称等价（字体内 name 表可能只写英文或中文）
NAME_EQUIV = {
    "微软雅黑": {"微软雅黑", "microsoft yahei", "microsoft yahei ui"},
    "黑体": {"黑体", "simhei"},
    "宋体": {"宋体", "simsun"},
    "思源黑体": {"思源黑体", "思源黑体 cn", "source han sans sc", "source han sans cn", "source han sans", "noto sans cjk sc",
               "noto sans sc", "思源黑體"},
}


def font_dirs():
    dirs = []
    env = os.environ.get("PPTLAB_FONT_DIRS")
    if env:
        dirs += [d for d in env.split(os.pathsep) if d]
    here = os.path.dirname(os.path.abspath(__file__))
    dirs += [os.path.join(here, "fonts"), os.path.join(here, "..", "fonts"), os.path.join(here, "..", "..", "fonts")]
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", "C:\\Windows")
        dirs += [os.path.join(windir, "Fonts"), os.path.join(home, "AppData", "Local", "Microsoft", "Windows", "Fonts")]
    elif sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts", os.path.join(home, "Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.join(home, ".fonts"), os.path.join(home, ".local/share/fonts")]
    return dirs


def _iter_font_files():
    seen = set()
    for d in font_dirs():
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.lower().endswith((".ttf", ".otf", ".ttc", ".otc")):
                    p = os.path.join(root, fn)
                    k = os.path.normcase(os.path.abspath(p))
                    if k not in seen:
                        seen.add(k)
                        yield p


class FontRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._found = {}  # family → [faces]
        self._files = None

    def _all_files(self):
        if self._files is None:
            self._files = list(_iter_font_files())
        return self._files

    def faces(self, family):
        key = (family or "").strip().lower()
        with self._lock:
            if key in self._found:
                return self._found[key]
            wanted = NAME_EQUIV.get(family, set()) | NAME_EQUIV.get(key, set()) | {key}
            hints = ALIASES.get(family, []) + ALIASES.get(key, [])
            files = self._all_files()
            ordered = [f for f in files if any(h in os.path.basename(f).lower() for h in hints)] if hints else []
            hit = []
            for f in ordered + [f for f in files if f not in ordered]:
                for face in _open_faces(f):
                    if face.names & wanted:
                        hit.append(face)
                if hit and f not in ordered:
                    break
                if hit and len(hit) >= 2:
                    break
            self._found[key] = hit
            return hit


_REG = FontRegistry()
_cache = {}
_enabled = os.environ.get("PPT_REAL_METRICS", "on").lower() != "off"


def set_real_metrics(on):
    global _enabled
    _enabled = bool(on)
    _cache.clear()


def real_metrics_enabled():
    return _enabled


_BUILTIN = None


def _builtin(family):
    """内置字宽表（data/metrics/*.json）：字体没装也能按真实字宽排版（一套通用黑体、一套西文；本机没有所选字体时拿通用黑体的字宽近似）"""
    global _BUILTIN
    if _BUILTIN is None:
        _BUILTIN = {}
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "metrics")
        if os.path.isdir(d):
            import json
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(d, fn), encoding="utf-8") as f:
                            m = json.load(f)
                    except (OSError, ValueError):
                        continue
                    for n in m.get("names") or []:
                        _BUILTIN.setdefault(n.lower(), m)
    return _BUILTIN.get((family or "").strip().lower())


def has_builtin_metrics(family):
    return _builtin(family) is not None


def _builtin_em(fam, ch):
    m = _builtin(fam)
    if not m:
        return None
    w = (m.get("widths") or {}).get(ch)
    if w is None and m.get("cjk") and is_cjk(ch):
        w = m["cjk"]
    return w


def _bundled_dirs():
    out = []
    env = os.environ.get("PPTLAB_FONT_DIRS")
    if env:
        out += [d for d in env.split(os.pathsep) if d]
    here = os.path.dirname(os.path.abspath(__file__))
    out += [os.path.join(here, "fonts"), os.path.join(here, "..", "fonts"), os.path.join(here, "..", "..", "fonts")]
    return [os.path.normcase(os.path.abspath(d)) + os.sep for d in out]


def font_installed(family):
    """字体是否装在系统里（只在 SKILL 包 fonts 目录里有不算：看稿的 PowerPoint 用不到它）"""
    key = (family or "").strip().lower()
    if key in _installed:
        return _installed[key]
    b = tuple(_bundled_dirs())
    wanted = NAME_EQUIV.get(family, set()) | NAME_EQUIV.get(key, set()) | {key}
    hints = ALIASES.get(family, []) + ALIASES.get(key, [])
    files = [f for f in _REG._all_files() if not os.path.normcase(os.path.abspath(f)).startswith(b)]
    ordered = [f for f in files if any(h in os.path.basename(f).lower() for h in hints)]
    ok = False
    for f in ordered + [f for f in files if f not in ordered]:
        if any(face.names & wanted for face in _open_faces(f)):
            ok = True
            break
    _installed[key] = ok
    return ok


_installed = {}


def font_available(family):
    return bool(_REG.faces(family))


def char_em(ch, font="微软雅黑", latin=None):
    """单字符 em 宽：常规/粗体取较宽者（留加粗余量）；CJK 用中文字体，其余用西文字体"""
    if not _enabled:
        return estimate_em(ch)
    fam = font if (latin is None or is_cjk(ch)) else latin
    key = (fam, ch)
    v = _cache.get(key)
    if v is not None:
        return v
    em = estimate_em(ch)
    best = None
    for face in _REG.faces(fam):
        w = face.advance_em(ch)
        if w is not None and (best is None or w > best):
            best = w
    if best is None:
        best = _builtin_em(fam, ch)
    if best is None and fam == font:  # 本机没有这个字体：借用内置的通用黑体字宽表（中文等宽，西文接近常见黑体）
        best = _builtin_em("思源黑体", ch)
    if best is None and fam != font:  # 西文字体缺字：退回中文字体
        for face in _REG.faces(font):
            w = face.advance_em(ch)
            if w is not None and (best is None or w > best):
                best = w
        if best is None:
            best = _builtin_em(font, ch)
    if best is not None and 0.15 < best < 1.6:
        em = best
    _cache[key] = em
    return em


def text_em(text, font="微软雅黑", latin=None):
    return sum(char_em(ch, font, latin) for ch in str(text or ""))
