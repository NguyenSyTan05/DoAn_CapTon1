"""
text_filters.py (modules/live_translate)
==========================================
Làm sạch văn bản nhận dạng và lọc "ảo giác" của Whisper.

Nguồn gốc (ghi rõ theo CLAUDE.md):
- [EXISTING / từ tan-main] clean_transcript_text, remove_repeated_phrases, chặn ký tự
  ngoại lai (Hàn, Thái, Ả Rập...) — viết lại từ unified_speech_recognizer.py.
- [EXISTING / từ FinalNCKH] danh sách câu rác YouTube và luật từ lặp (ai_service.py).
- [CUSTOM — điều chỉnh của nhóm] Các câu ngắn hay bị Whisper bịa khi im lặng ("thank you",
  "cảm ơn", "yes", "ok"...) CHỈ bị chặn khi độ tin cậy thấp (no_speech_prob cao hoặc
  avg_logprob thấp). Hai bản gốc chặn tuyệt đối nên làm mất câu trả lời ngắn thật của lớp.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
# Chỉ đúng các ký tự có dấu của tiếng Việt (NFC). Bản cũ dùng dải [À-ỹ] nên vô tình coi cả
# chữ Hy Lạp, Do Thái, Ấn Độ, ñ, ü, ç... là "tiếng Việt".
_VI_DIACRITICS = re.compile(
    "[àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴĐ]"
)
# Ký tự CHỈ có trong tiếng Việt (không trùng tiếng Pháp/Ý/TBN như è, é, à, ò, ù, í)
_VI_SPECIFIC = re.compile(
    "[ăâđêôơưảãạẳẵặẩẫậẻẽẹểễệỉĩịỏõọổỗộởỡợủũụửữựỳỷỹỵắằấầếềốồớờứừ"
    "ĂÂĐÊÔƠƯẢÃẠẲẴẶẨẪẬẺẼẸỂỄỆỈĨỊỎÕỌỔỖỘỞỠỢỦŨỤỬỮỰỲỶỸỴẮẰẤẦẾỀỐỒỚỜỨỪ]"
)
_VI_UNACCENTED = {
    "toi", "ban", "anh", "em", "co", "la", "va", "khong", "nguoi", "trong", "cho", "di",
    "ve", "lam", "nay", "do", "duoc", "ra", "vao", "voi", "den", "theo", "biet", "noi",
    "nhung", "thi", "ma", "cac", "lop", "hoc", "bai", "thay", "da", "se", "dang", "con",
    "mot", "hai", "ba", "xin", "chao", "giang", "vien",
}

# Chữ viết ngoài song ngữ Anh–Việt: Hangul, Georgian, CJK, Kana, Cyrillic, Arabic, Thai
_FOREIGN_SCRIPTS = re.compile(
    "[가-힣ᄀ-ᇿႠ-ჿᲐ-Ჺ一-鿿㐀-䶿"
    "぀-ヿЀ-ӿ؀-ۿ฀-๿]"
)

# Ký tự rác Latin-1 / mojibake không bao giờ có trong tiếng Anh hoặc tiếng Việt
_GARBAGE_LATIN = re.compile(r"[þÞßæÆøØñÑåÅäÄöÖüÜïÏëËîÎðÐ×÷\ufffd]")

# Câu rác do phụ đề YouTube / nhạc nền: luôn chặn
_ARTIFACTS = (
    "subscribe", "la la school", "like and share", "like and subscribe", "dang ky kenh",
    "đăng ký kênh", "hen gap lai", "hẹn gặp lại", "chia se video", "subtitles by",
    "để không bỏ lỡ", "bấm chuông", "amara.org",
    "ghiền mì gõ", "fap tv", "storm meeting done",
)

# Câu tiếng Anh "học vẹt" Whisper bịa ra từ tiếng thở/nhiễu. Khi giảng viên ép lang="vi" thì
# chặn tuyệt đối (theo unified_speech_recognizer.py); ở chế độ khác chỉ chặn khi độ tin cậy thấp.
_EN_PARROT_PHRASES = {
    "thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "bye bye",
    "bye now", "goodbye", "you", "you know", "i'm not", "i am not", "i see the light",
    "i'm coming", "i am coming", "i'm cold", "i'm single", "i know", "that is so", "big way",
    "big big way", "welcome back", "see you next time", "see you later", "the end",
    "storm meeting done",
}

# Câu ngắn Whisper hay bịa khi im lặng nhưng CŨNG có thể là lời thật ("ok các em", "yes",
# "dạ"): chỉ chặn khi độ tin cậy thấp, kể cả ở chế độ lang="vi".
_SILENCE_PHRASES = _EN_PARROT_PHRASES | {
    "yeah", "yes", "no", "ok", "okay", "all right", "alright", "hey", "so",
    "cảm ơn", "cảm ơn các bạn", "cảm ơn đã xem", "cam on", "vâng", "dạ",
}

# Ảo giác tiếng Latin/Romance ngoại lai khi để chế độ auto
_ROMANCE_LEAK = re.compile(
    r"\b(non\s+è|della|delle|nostra|nostro|allora|ematina|cabe\s+aí|vamos\s+a|jij\s+bent\s+het)\b",
    re.IGNORECASE,
)

NO_SPEECH_LIMIT = 0.4   # trên mức này coi câu ngắn là ảo giác
LOGPROB_LIMIT = -1.0    # dưới mức này coi câu ngắn là ảo giác


def normalize_text(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", text or "")).strip()


def clean_transcript_text(text: str) -> str:
    """NFC, dọn khoảng trắng quanh dấu câu, viết hoa đầu câu. Không đổi từ nào người nói."""
    s = normalize_text(text)
    if not s:
        return ""
    s = re.sub(r"\s+([,\.!\?:;])", r"\1", s)
    s = re.sub(r"([,\.!\?:;])([^\s0-9])", r"\1 \2", s)
    s = _WS.sub(" ", s).strip()
    s = re.sub(r"(^|[.!?]\s+)([^\W\d_])", lambda m: m.group(1) + m.group(2).upper(), s, flags=re.UNICODE)
    return s


def _tok(t: str) -> str:
    return re.sub(r"^[^\w\s]+|[^\w\s]+$", "", t).lower()


def remove_repeated_phrases(text: str) -> str:
    """Bỏ vòng lặp bất thường của decoder. Từ đơn chỉ bị coi là lặp khi xuất hiện >= 3 lần
    liên tiếp (giữ từ láy tiếng Việt như "luôn luôn", "từ từ"); cụm >= 2 từ lặp >= 2 lần."""
    current = (text or "").strip()
    for _ in range(3):
        tokens = re.findall(r"\S+", current)
        n = len(tokens)
        if n <= 1:
            break
        out: list[str] = []
        i = 0
        changed = False
        while i < n:
            matched = False
            for plen in range(1, min(15, (n - i) // 2 + 1)):
                phrase = [_tok(tokens[i + k]) for k in range(plen)]
                if not any(phrase):
                    continue
                repeats, j = 1, i + plen
                while j + plen <= n and [_tok(tokens[j + k]) for k in range(plen)] == phrase:
                    repeats += 1
                    j += plen
                if (plen == 1 and repeats >= 3) or (plen > 1 and repeats >= 2):
                    out.extend(tokens[i : i + plen])
                    i, matched, changed = j, True, True
                    break
            if not matched:
                out.append(tokens[i])
                i += 1
        current = re.sub(r"([,\.!?])(\s*\1)+", r"\1", " ".join(out))
        if not changed:
            break
    return re.sub(r",\s*$", "", current).strip()


def _has_vietnamese_signal(text: str) -> bool:
    if _VI_DIACRITICS.search(text):
        return True
    words = set(re.findall(r"[a-z]+", text.lower()))
    return bool(words & _VI_UNACCENTED)


def is_hallucination(
    text: str,
    *,
    no_speech_prob: float = 0.0,
    avg_logprob: float = 0.0,
    forced_lang: str | None = None,
    detected_lang: str | None = None,
) -> bool:
    """True nếu `text` nhiều khả năng là ảo giác/nhiễu chứ không phải lời nói thật."""
    normalized = normalize_text(text).casefold()
    if not re.search(r"[\w]", normalized, flags=re.UNICODE):
        return True
    if _FOREIGN_SCRIPTS.search(normalized):
        return True
    if _GARBAGE_LATIN.search(text or ""):
        return True
    if any(a in normalized for a in _ARTIFACTS):
        return True
    if re.search(r"\b(\w+)(?:\s+\1\b){2,}", normalized):  # "live live live"
        return True
    # "aaaaaa", "hmmmmm" — chỉ xét CHỮ CÁI để không chặn nhầm số như "100000"
    if re.search(r"([^\W\d_])\1{4,}", normalized, flags=re.UNICODE):
        return True
    words = normalized.split()
    if len(words) >= 5:
        unique = set(words)
        if len(unique) / len(words) < 0.35 or len(unique) <= 2:
            return True

    has_vi = _has_vietnamese_signal(normalized)
    # Whisper hay dùng nháy cong (’) — đổi về nháy thẳng trước khi so khớp cụm câu
    bare = _WS.sub(" ", re.sub(r"[^\w\s']", "", normalized.replace("\u2019", "'"))).strip()

    if forced_lang is None:
        if _ROMANCE_LEAK.search(normalized) and not _VI_SPECIFIC.search(normalized):
            return True
        if detected_lang not in (None, "en", "vi") and not has_vi:
            return True

    if forced_lang == "vi" and not has_vi and bare in _EN_PARROT_PHRASES:
        return True

    if bare in _SILENCE_PHRASES:
        return no_speech_prob > NO_SPEECH_LIMIT or avg_logprob < LOGPROB_LIMIT
    return False


def decide_language(text: str, whisper_lang: str | None = None, whisper_prob: float = 0.0) -> str:
    """Trả về "vi" hoặc "en". Ưu tiên dấu tiếng Việt trong chữ; sau đó tin Whisper khi nó báo
    en/vi; cuối cùng mới dùng từ Việt không dấu."""
    if _VI_DIACRITICS.search(text or ""):
        return "vi"
    if whisper_lang in ("en", "vi"):
        return whisper_lang
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return "vi" if words & _VI_UNACCENTED else "en"


def finalize_text(text: str) -> str:
    """Chuỗi chuẩn hoá hiển thị dùng sau khi STT: dọn ký tự + khử lặp."""
    return remove_repeated_phrases(clean_transcript_text(text))
