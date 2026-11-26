#!/usr/bin/env python3
"""打包技能：python tools/build_skill.py [--out dist] [--no-runtime]

产物：
  dist/myppt/                 解压即用的目录（技能根目录 = SKILL.md 所在的文件夹）
  dist/myppt-<版本>.zip       完整包（含 Windows 自带 Python，电脑上没装 Python 也能用）
  dist/myppt-<版本>-lite.zip  精简包（需本机 Python 3.8+）

不带任何字体，也不要求安装字体。Windows Python 首次打包时下载到 tools/cache/（不进 git）。
"""
import io
import os
import shutil
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")
PY_VER = "3.12.10"
VERSION = "0.1.0"
FILES = ["SKILL.md", "README.md", "LICENSE", "run.py", "myppt.cmd", "myppt.sh"]
DIRS = ["myppt"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/4.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


# Windows Python 里用不到的部分（排版引擎只用 json/re/zipfile/struct/math 等）
_PY_DROP_DIRS = ["include", "libs", "Lib/test", "Lib/idlelib", "Lib/tkinter", "Lib/turtledemo", "Lib/ensurepip",
                 "Lib/lib2to3", "Lib/site-packages", "Lib/pydoc_data", "Lib/venv", "Lib/sqlite3", "Lib/asyncio",
                 "Lib/xmlrpc", "Lib/multiprocessing", "Lib/concurrent", "Lib/wsgiref", "Lib/msilib", "Lib/curses",
                 "Lib/dbm", "Lib/distutils", "tcl"]
_PY_DROP_FILES = ["Lib/turtle.py", "DLLs/_tkinter.pyd", "DLLs/_ssl.pyd", "DLLs/libssl-3.dll", "DLLs/libcrypto-3.dll",
                  "DLLs/_hashlib.pyd", "DLLs/sqlite3.dll", "DLLs/_sqlite3.pyd", "DLLs/_msi.pyd", "DLLs/winsound.pyd",
                  "pythonw.exe"]


def ensure_runtime():
    d = os.path.join(CACHE, "runtime-%s" % PY_VER)
    if os.path.exists(os.path.join(d, "python.exe")):
        return d
    print("下载 Windows Python %s…" % PY_VER)
    pkg = _get("https://api.nuget.org/v3-flatcontainer/python/%s/python.%s.nupkg" % (PY_VER, PY_VER))
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(pkg)) as z:
        for n in z.namelist():
            if n.startswith("tools/") and not n.endswith("/"):
                p = os.path.join(tmp, n[len("tools/"):])
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(z.read(n))
    for x in _PY_DROP_DIRS:
        shutil.rmtree(os.path.join(tmp, x), ignore_errors=True)
    for x in _PY_DROP_FILES:
        p = os.path.join(tmp, x)
        if os.path.exists(p):
            os.remove(p)
    for root, dirs, _ in os.walk(tmp):
        for dd in list(dirs):
            if dd == "__pycache__":
                shutil.rmtree(os.path.join(root, dd))
                dirs.remove(dd)
    for dd in os.listdir(os.path.join(tmp, "DLLs")):
        if dd.startswith(("tcl", "tk")):
            os.remove(os.path.join(tmp, "DLLs", dd))
    os.rename(tmp, d)
    return d


def _ignore(_, names):
    return [n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo", ".pptx", ".jpg", ".pdf"))]


def build(out, runtime=True):
    dst = os.path.join(out, "myppt")
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for f in FILES:
        shutil.copy2(os.path.join(ROOT, f), os.path.join(dst, f))
    for d in DIRS:
        shutil.copytree(os.path.join(ROOT, d), os.path.join(dst, d), ignore=_ignore)
    for root, _, files in os.walk(dst):  # .cmd 用 CRLF，.sh 用 LF
        for fn in files:
            p = os.path.join(root, fn)
            if fn.endswith((".cmd", ".sh")):
                with open(p, "rb") as f:
                    b = f.read().replace(b"\r\n", b"\n")
                if fn.endswith(".cmd"):
                    b = b.replace(b"\n", b"\r\n")
                with open(p, "wb") as f:
                    f.write(b)
    lite = os.path.join(out, "myppt-%s-lite.zip" % VERSION)
    _zip(dst, lite)
    full = None
    if runtime:
        shutil.copytree(ensure_runtime(), os.path.join(dst, "runtime"))
        full = os.path.join(out, "myppt-%s.zip" % VERSION)
        _zip(dst, full)
    return dst, full, lite


def _zip(src, path):
    if os.path.exists(path):
        os.remove(path)
    base = os.path.dirname(src)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _, files in os.walk(src):
            for fn in sorted(files):
                p = os.path.join(root, fn)
                zi = zipfile.ZipInfo.from_file(p, os.path.relpath(p, base).replace(os.sep, "/"))
                if fn.endswith(".sh") or fn == "run.py":
                    zi.external_attr = 0o100755 << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(p, "rb") as f:
                    z.writestr(zi, f.read(), compresslevel=9)


def main(argv):
    out = os.path.join(ROOT, "dist")
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    os.makedirs(out, exist_ok=True)
    dst, full, lite = build(out, runtime="--no-runtime" not in argv)
    print("目录：%s" % dst)
    for p in (full, lite):
        if p:
            print("%s  %.1f MB" % (p, os.path.getsize(p) / 1048576.0))


if __name__ == "__main__":
    main(sys.argv[1:])
