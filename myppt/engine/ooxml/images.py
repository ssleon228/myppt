"""图片：识别格式与像素尺寸（纯标准库读文件头）。"""
import struct

MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
}


def sniff(data):
    """返回 (ext, width, height)；无法识别时 (None, 0, 0)"""
    if not data or len(data) < 12:
        return None, 0, 0
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:2] == b"\xff\xd8":
        return ("jpeg",) + _jpeg_size(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return "gif", w, h
    if data[:2] == b"BM" and len(data) >= 26:
        w, h = struct.unpack("<ii", data[18:26])
        return "bmp", abs(w), abs(h)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ("webp",) + _webp_size(data)
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff", 0, 0
    head = data[:512].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return "svg", 0, 0
    if data[:4] == b"\x01\x00\x00\x00" and data[40:44] == b" EMF":
        return "emf", 0, 0
    if data[:4] == b"\xd7\xcd\xc6\x9a":
        return "wmf", 0, 0
    return None, 0, 0


def _jpeg_size(data):
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return 0, 0


def _webp_size(data):
    chunk = data[12:16]
    try:
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L":
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return w, h
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return w, h
    except Exception:
        pass
    return 0, 0
