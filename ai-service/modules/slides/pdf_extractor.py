"""
pdf_extractor.py (modules/slides)
===================================
Bộ trích xuất văn bản theo từng trang từ tệp PDF Slide bài giảng:
1. Ưu tiên dùng `pypdf` hoặc `pdfplumber` nếu môi trường đã cài đặt.
2. Tích hợp sẵn bộ giải mã luồng PDF thuần Python (`zlib` FlateDecode + ánh xạ
   bảng mã `ToUnicode` CMap + chuỗi UTF-16BE / PDF literal trong khối `BT...ET`)
   để bóc tách nội dung Slide ngay cả khi không cài thư viện ngoài.
"""

from __future__ import annotations

import io
import logging
import re
import zlib

logger = logging.getLogger("classbridge.pdf_extractor")

_STREAM_RE = re.compile(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_BT_ET_RE = re.compile(rb"BT\b(.*?)\bET", re.DOTALL)
_CMAP_BFRANGE_RE = re.compile(
    rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>"
)
_CMAP_BFCHAR_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_TOKEN_STR_RE = re.compile(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>")


def _clean_page_text(raw: str, max_chars: int = 4000) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    compact = "\n".join(ln for ln in lines if ln)
    return compact[:max_chars].strip()


def _extract_with_optional_libs(pdf_bytes: bytes, max_pages: int) -> dict[int, str] | None:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages: dict[int, str] = {}
        for idx, page in enumerate(reader.pages[:max_pages], start=1):
            cleaned = _clean_page_text(page.extract_text() or "")
            if cleaned:
                pages[idx] = cleaned
        return pages
    except ImportError:
        pass
    except Exception:
        logger.debug("pypdf không đọc được file PDF, chuyển sang trình giải mã nội bộ", exc_info=True)

    try:
        import pdfplumber  # type: ignore[import-not-found]

        pages = {}
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages[:max_pages], start=1):
                cleaned = _clean_page_text(page.extract_text() or "")
                if cleaned:
                    pages[idx] = cleaned
        return pages
    except ImportError:
        return None
    except Exception:
        logger.debug("pdfplumber không đọc được file PDF, chuyển sang trình giải mã nội bộ", exc_info=True)
        return None


def _parse_cmap(stream_data: bytes) -> dict[int, str]:
    mapping: dict[int, str] = {}
    if b"beginbfchar" not in stream_data and b"beginbfrange" not in stream_data:
        return mapping
    for m in _CMAP_BFCHAR_RE.finditer(stream_data):
        src_hex, dst_hex = m.group(1), m.group(2)
        try:
            code = int(src_hex, 16)
            dst_bytes = bytes.fromhex(dst_hex.decode("ascii"))
            mapping[code] = dst_bytes.decode("utf-16-be", errors="ignore")
        except ValueError:
            continue
    for m in _CMAP_BFRANGE_RE.finditer(stream_data):
        start_hex, end_hex, target_hex = m.group(1), m.group(2), m.group(3)
        try:
            start_code = int(start_hex, 16)
            end_code = int(end_hex, 16)
            base_val = int(target_hex, 16)
            if end_code - start_code > 512:
                continue
            width = max(2, len(target_hex) // 2)
            for offset in range(end_code - start_code + 1):
                val_bytes = (base_val + offset).to_bytes(width, "big", signed=False)
                mapping[start_code + offset] = val_bytes.decode("utf-16-be", errors="ignore")
        except (ValueError, OverflowError):
            continue
    return mapping


def _decode_pdf_literal(token: bytes) -> bytes:
    inner = token[1:-1]
    out = bytearray()
    i = 0
    n = len(inner)
    escapes = {
        ord("n"): b"\n",
        ord("r"): b"\r",
        ord("t"): b"\t",
        ord("b"): b"\b",
        ord("f"): b"\f",
        ord("("): b"(",
        ord(")"): b")",
        ord("\\"): b"\\",
    }
    while i < n:
        ch = inner[i]
        if ch == 0x5C and i + 1 < n:
            nxt = inner[i + 1]
            if nxt in escapes:
                out.extend(escapes[nxt])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:
                oct_digits = bytes([nxt])
                j = i + 2
                while j < n and j < i + 4 and 0x30 <= inner[j] <= 0x37:
                    oct_digits += bytes([inner[j]])
                    j += 1
                out.append(int(oct_digits, 8) & 0xFF)
                i = j
                continue
            if nxt in (0x0A, 0x0D):
                i += 2
                continue
            out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return bytes(out)


def _decode_text_token(token: bytes, cmap: dict[int, str]) -> str:
    if token.startswith(b"<") and token.endswith(b">"):
        hex_str = re.sub(rb"\s+", b"", token[1:-1]).decode("ascii", errors="ignore")
        if len(hex_str) % 2 == 1:
            hex_str += "0"
        raw = bytes.fromhex(hex_str)
    else:
        raw = _decode_pdf_literal(token)

    if not raw:
        return ""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="ignore")
    if cmap:
        if len(raw) % 2 == 0 and any(( (raw[k] << 8) | raw[k + 1] ) in cmap for k in range(0, len(raw), 2)):
            chars = []
            for k in range(0, len(raw), 2):
                code = (raw[k] << 8) | raw[k + 1]
                chars.append(cmap.get(code, ""))
            mapped = "".join(chars)
            if mapped.strip():
                return mapped
        mapped_single = "".join(cmap.get(b, chr(b) if 32 <= b < 127 else "") for b in raw)
        if mapped_single.strip():
            return mapped_single
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="ignore")


def extract_pdf_pages_text(pdf_bytes: bytes, max_pages: int = 80) -> dict[int, str]:
    """Trả về từ điển `{số_trang_bắt_đầu_từ_1: nội_dung_văn_bản}` của tệp PDF."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF-"):
        return {}

    via_lib = _extract_with_optional_libs(pdf_bytes, max_pages=max_pages)
    if via_lib is not None:
        return via_lib

    decompressed_streams: list[bytes] = []
    global_cmap: dict[int, str] = {}

    for match in _STREAM_RE.finditer(pdf_bytes):
        header, body = match.group(1), match.group(2)
        data = body
        if b"/FlateDecode" in header:
            try:
                data = zlib.decompress(body)
            except zlib.error:
                try:
                    data = zlib.decompress(body.strip(b"\r\n"))
                except zlib.error:
                    continue
        elif any(flt in header for flt in (b"/DCTDecode", b"/JPXDecode", b"/JBIG2Decode")):
            continue

        cmap_part = _parse_cmap(data)
        if cmap_part:
            global_cmap.update(cmap_part)
            continue
        if b"BT" in data and b"ET" in data:
            decompressed_streams.append(data)

    pages: dict[int, str] = {}
    page_no = 1
    for stream in decompressed_streams:
        if page_no > max_pages:
            break
        blocks: list[str] = []
        for bt_match in _BT_ET_RE.finditer(stream):
            bt_body = bt_match.group(1)
            fragments = [
                _decode_text_token(tok.group(0), global_cmap)
                for tok in _TOKEN_STR_RE.finditer(bt_body)
            ]
            line = " ".join(frag.strip() for frag in fragments if frag.strip())
            if line:
                blocks.append(line)
        cleaned = _clean_page_text("\n".join(blocks))
        if cleaned:
            pages[page_no] = cleaned
            page_no += 1

    return pages
