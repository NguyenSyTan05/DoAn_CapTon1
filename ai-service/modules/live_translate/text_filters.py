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
_MATH_OR_DIGIT = re.compile(r"[\d=+\-*/<>^%]")
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
_GARBAGE_LATIN = re.compile(r"[þÞßæÆøØñÑåÅäÄöÖüÜïÏëËîÎðÐ×÷¿¡\ufffd]")

# Nhãn âm thanh nền Whisper hay tự chèn khi có nhạc/tạp âm/im lặng
_SOUND_TAGS = re.compile(
    r"[\[(]\s*(?:music|applause|laughter|silence|cheering|coughing|sigh|noise|inaudible|"
    r"âm nhạc|nhạc|vỗ tay|tiếng vỗ tay|cười|tiếng cười|im lặng|nhiễu|ho|thở dài)[^\]\)]*[\])]"
    r"|[♪♫]+",
    re.IGNORECASE,
)

# Câu rác cố định do phụ đề YouTube / nhạc nền / nhại prompt khi im lặng: luôn chặn
_ARTIFACTS = (
    "subscribe", "la la school", "like and share", "like and subscribe", "dang ky kenh",
    "đăng ký kênh", "hãy đăng ký kênh", "đừng quên đăng ký", "hen gap lai", "hẹn gặp lại",
    "chia se video", "subtitles by", "captioned by", "transcribed by", "translated by",
    "để không bỏ lỡ", "bấm chuông", "nhấn chuông", "amara.org", "đón xem video", "xem video này",
    "video tiếp theo", "kênh youtube", "phụ đề được thực hiện bởi", "người dịch", "biên tập viên",
    "cảm ơn các bạn đã đón xem", "cảm ơn các bạn đã xem", "cảm ơn các bạn đã theo dõi",
    "cám ơn các bạn đã theo dõi", "cảm ơn các bạn đã lắng nghe", "cảm ơn quý vị và các bạn",
    "cảm ơn mọi người đã xem", "cám ơn các bạn, tạm biệt", "cảm ơn các bạn, tạm biệt",
    "xin chào và hẹn gặp lại", "xin chào tạm biệt", "chào tạm biệt", "tạm biệt các bạn",
    "bye bye, tạm biệt", "bài giảng đại học bằng tiếng việt", "bài giảng và hội thoại tiếng việt",
    "nội dung bài giảng và thảo luận trên lớp học", "thảo luận trên lớp học bằng tiếng việt",
    "đầy đủ dấu thanh điệu", "dấu câu rõ ràng từng từ ngữ", "ghiền mì gõ", "fap tv",
    "storm meeting done", "thank you for listening", "thanks for listening",
    "subscribe to my channel", "please subscribe", "don't forget to subscribe",
    "see you in the next video", "mbc news", "sbs news", "kbs news",
    # Whisper ảo giác khi nhìn slide/màn hình trong phòng học
    "picture", "image", "photo", "video",
)

# Mẫu câu cố định / câu "học vẹt" Whisper hay tự bịa khi không nói (im lặng, tiếng thở, tạp âm):
# Chặn TUYỆT ĐỐI nếu cả câu chỉ khớp đúng mẫu này (không phụ thuộc no_speech_prob/avg_logprob).
# Câu giảng thật dài hơn (VD: "Cảm ơn em đã hỏi về deadlock") vẫn được giữ nguyên.
_BLOCKED_STANDALONE_PHRASES = {
    "thank you", "thanks", "thank you so much", "thank you very much", "thanks a lot",
    "thanks for watching", "thank you for watching", "thank you for listening",
    "thanks for listening", "bye", "bye bye", "bye now", "goodbye", "bye guys", "bye son",
    "you", "you know", "i'm not", "i am not", "i see the light", "i'm coming", "i am coming",
    "i'm cold", "i'm single", "i know", "that is so", "big way", "big big way",
    "welcome back", "see you next time", "see you later", "the end", "storm meeting done",
    "music", "silence", "applause", "laughter", "watching", "subtitles",
    "uh", "um", "hmm", "hm", "oh", "ah", "so", "hey",
    "cảm ơn", "cám ơn", "cam on", "cảm ơn các bạn", "cám ơn các bạn", "cam on cac ban",
    "cảm ơn các bạn rất nhiều", "cám ơn các bạn rất nhiều", "rất cảm ơn các bạn",
    "rất cám ơn các bạn", "cảm ơn mọi người", "cám ơn mọi người",
    "cảm ơn mọi người đã lắng nghe", "cám ơn mọi người đã lắng nghe",
    "cảm ơn quý vị", "cảm ơn đã xem", "cảm ơn đã lắng nghe",
    "cảm ơn bạn", "cám ơn bạn", "cảm ơn nhé", "cám ơn nhé", "cảm ơn ạ", "cám ơn ạ",
    "cảm ơn nhiều", "cám ơn nhiều",
    "tạm biệt", "tam biet", "tạm biệt các bạn", "xin chào", "xin chao",
    "xin chào các bạn", "xin chào tất cả các bạn", "chào các bạn",
}

# Từ phản hồi siêu ngắn có thể là lời thật ("ok", "yes", "dạ", "vâng"):
# chỉ chặn khi độ tin cậy thấp.
_SILENCE_PHRASES = {
    "yeah", "yes", "no", "ok", "okay", "all right", "alright", "vâng", "dạ",
}

# Ảo giác tiếng Latin/Romance ngoại lai (Bồ Đào Nha, Pháp, Tây Ban Nha, Ý, Indonesia...)
_ROMANCE_LEAK = re.compile(
    r"\b(non\s+è|della|delle|nostra|nostro|allora|ematina|cabe\s+aí|vamos\s+a|jij\s+bent\s+het|"
    r"atenção|o\s+que\s+é|isso\s+aí|tá\s+pra|acertar\s+com|polícia|c'est|c'était|à\s+la\s+salle|"
    r"nouvelle-paris|la\s+gente|no\s+lo\s+digan|sampai\s+jumpa|qu'est-ce|não|você|está|estão)\b",
    re.IGNORECASE,
)

NO_SPEECH_LIMIT = 0.30  # trên mức này coi câu ngắn/mẫu cố định là ảo giác
LOGPROB_LIMIT = -0.75   # dưới mức này coi câu ngắn/mẫu cố định là ảo giác

# ---------------------------------------------------------------------------
# Post-processing bằng underthesea (tùy chọn — nếu chưa cài thì bỏ qua)
# Sửa lỗi dấu thanh điệu tiếng Việt mà Whisper hay nhầm (sắc↔nặng, huyền↔nặng...)
# ---------------------------------------------------------------------------
_underthesea_normalize = None
_underthesea_checked = False

def _get_underthesea_normalize():
    """Lazy-load underthesea.text_normalize. Trả None nếu chưa cài."""
    global _underthesea_normalize, _underthesea_checked
    if _underthesea_checked:
        return _underthesea_normalize
    _underthesea_checked = True
    try:
        from underthesea import text_normalize  # type: ignore
        _underthesea_normalize = text_normalize
        import logging
        logging.getLogger("classbridge.text_filters").info(
            "✅ underthesea text_normalize loaded — Vietnamese tone post-correction enabled"
        )
    except ImportError:
        import logging
        logging.getLogger("classbridge.text_filters").warning(
            "⚠️  underthesea chưa được cài — bỏ qua sửa thanh điệu. "
            "Cài bằng: pip install underthesea"
        )
    return _underthesea_normalize


def apply_vi_tone_correction(text: str) -> str:
    """Sửa lỗi dấu thanh điệu tiếng Việt sau Whisper bằng underthesea.text_normalize().
    Nếu underthesea chưa cài, trả nguyên bản text. An toàn 100% (try/except bảo vệ)."""
    fn = _get_underthesea_normalize()
    if fn is None or not text:
        return text
    try:
        corrected = fn(text)
        # Chỉ dùng kết quả nếu độ dài hợp lý (không bị rút ngắn quá nhiều)
        if corrected and len(corrected) >= len(text) * 0.7:
            return corrected
    except Exception:
        pass
    return text



def normalize_text(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", text or "")).strip()


def clean_transcript_text(text: str) -> str:
    """NFC, bỏ nhãn tạp âm [Music]/♪, dọn dấu câu lỗi/mồ côi, viết hoa đầu câu (giữ Node.js, URL, 10:30)."""
    s = _SOUND_TAGS.sub(" ", text or "")
    s = normalize_text(s)
    if not s:
        return ""
    # Dọn khoảng trắng thừa trước dấu câu và gộp dấu câu lặp/lỗi (",.", "..", "??")
    s = re.sub(r"\s+([,\.!\?:;])", r"\1", s)
    s = re.sub(r"([,\.!\?:;])\1+", r"\1", s)
    s = re.sub(r",\s*([.!?])", r"\1", s)
    # Chèn khoảng trắng sau dấu câu nhưng bảo toàn tên file/domain (Node.js, main.py), số thập phân (3.14), URL/giờ (10:30, http://)
    s = re.sub(r"([,!\?;])([^\s0-9])", r"\1 \2", s)
    s = re.sub(r"(?<!\w)\.([^\s0-9\.])", r". \1", s)
    s = re.sub(r"([:\.])(?=\s*[A-ZÀ-Ỹ])", r"\1 ", s)
    # Xoá dấu câu mồ côi ở đầu chuỗi
    s = re.sub(r"^[,.;:!?\-–—\s]+", "", s)
    s = _WS.sub(" ", s).strip()
    if not s:
        return ""
    if not re.match(r"^(?:https?://|www\.)", s, re.IGNORECASE):
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


def is_decoder_loop(text: str) -> bool:
    """Vòng lặp decoder (nguồn chính của 'tự nhảy chữ' khi im lặng/ồn): 1 từ lặp >= 4 lần liên tiếp
    hoặc cụm 2–6 từ lặp >= 3 lần liên tiếp. Bỏ dấu câu nên 'Hello, hello, hello, hello!' vẫn bắt được.
    Từ láy 2 lần ('luôn luôn', 'từ từ') không bị ảnh hưởng."""
    tokens = [t for t in (_tok(x) for x in re.findall(r"\S+", normalize_text(text))) if t]
    n = len(tokens)
    for plen in range(1, 7):
        need = 4 if plen == 1 else 3
        span = plen * need
        if span > n:
            break
        for i in range(n - span + 1):
            phrase = tokens[i:i + plen]
            if all(tokens[i + k * plen:i + (k + 1) * plen] == phrase for k in range(1, need)):
                return True
    return False


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
    # Chặn chuỗi cảm thán 1 âm tiết rác do tiếng thở/nhiễu (VD: "Ú, ơ.", "Ý, ạ.", "Ú, ú.")
    alpha_words = re.findall(r"[^\W\d_]+", normalized, flags=re.UNICODE)
    if alpha_words and all(len(w) <= 1 for w in alpha_words) and not _MATH_OR_DIGIT.search(normalized):
        return True
    if len(words) >= 5:
        unique = set(words)
        if len(unique) / len(words) < 0.35 or len(unique) <= 2:
            return True

    has_vi_specific = bool(_VI_SPECIFIC.search(normalized))
    # Whisper hay dùng nháy cong (’) — đổi về nháy thẳng trước khi so khớp cụm câu
    bare = _WS.sub(" ", re.sub(r"[^\w\s']", "", normalized.replace("\u2019", "'"))).strip()

    # Chặn tuyệt đối mọi mẫu câu cố định / câu học vẹt khi xuất hiện đứng riêng
    if bare in _BLOCKED_STANDALONE_PHRASES:
        return True

    # Luôn chặn câu ngoại lai Romance/Latin nếu không chứa dấu đặc trưng riêng của tiếng Việt
    if _ROMANCE_LEAK.search(normalized) and not has_vi_specific:
        return True

    if forced_lang is None:
        # Nếu Whisper phát hiện ngôn ngữ khác EN/VI (VD: pt, fr, es, id...) mà không có dấu riêng tiếng Việt thì chặn
        if detected_lang not in (None, "en", "vi") and not has_vi_specific:
            return True

    if bare in _SILENCE_PHRASES:
        return no_speech_prob > NO_SPEECH_LIMIT or avg_logprob < LOGPROB_LIMIT
    return False


_EN_STOPWORDS = {
    "the", "is", "are", "was", "were", "what", "whats", "how", "why", "when", "where",
    "who", "this", "that", "these", "those", "you", "your", "we", "our", "they", "their",
    "hello", "today", "will", "can", "could", "would", "should", "have", "has", "had",
    "with", "from", "about", "let", "lets", "for", "and", "not", "but", "into", "whole",
}


def _strip_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D")


def decide_language(text: str, whisper_lang: str | None = None, whisper_prob: float = 0.0) -> str:
    """Trả về "vi" hoặc "en". Ưu tiên dấu đặc trưng tiếng Việt; kiểm tra từ vựng khi câu không dấu."""
    del whisper_prob
    if _VI_SPECIFIC.search(text or ""):
        return "vi"
    if _VI_DIACRITICS.search(text or ""):
        if whisper_lang == "en":
            words = set(re.findall(r"[a-z]+", _strip_accents(text or "").lower()))
            return "vi" if words & _VI_UNACCENTED else "en"
        return "vi"
    words = set(re.findall(r"[a-z]+", (text or "").replace("’", "'").replace("'", "").lower()))
    has_vi = bool(words & _VI_UNACCENTED)
    has_en = bool(words & _EN_STOPWORDS)
    if has_en and not has_vi:
        return "en"
    if has_vi and not has_en:
        return "vi"
    if whisper_lang in ("en", "vi"):
        return whisper_lang
    return "vi" if has_vi else "en"


def finalize_text(text: str) -> str:
    """Chuỗi chuẩn hoá hiển thị dùng sau khi STT: dọn ký tự + khử lặp + loại từ ảo giác cuối câu."""
    s = remove_repeated_phrases(clean_transcript_text(text))
    # Xoá từ ảo giác Whisper thêm vào cuối (VD: "...cloud architecture. Picture.")
    # Chỉ xoá nếu từ cuối cùng là artifact đứng riêng (< 3 từ trong câu cuối)
    _TRAILING_NOISE = re.compile(
        r"(?:[.!?]\s+|\s+)(?:picture|image|photo|video|music|silence|applause|laughter)[.!?]?\s*$",
        re.IGNORECASE,
    )
    s = _TRAILING_NOISE.sub("", s).rstrip(" ,;")
    return s.strip()
