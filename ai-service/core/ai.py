"""
ai.py (core)
=============
Singleton AiService (Whisper STT + NLLB-200 MT) dùng chung cho cả process.

Nhiều cụm cùng cần đúng 1 instance này (mô hình chỉ được nạp 1 lần, mọi lời
gọi STT/MT đi qua cùng một threading.Lock bên trong AiService):
  - modules/live_translate/router.py  — dịch trực tiếp
  - modules/translate/router.py       — nút "Dịch" theo yêu cầu
  - core/lifespan.py                  — nạp model lúc khởi động và làm
                                        translator cho aggregator
Đặt ở core/ để không cụm nào phải import router của cụm khác.
"""

from __future__ import annotations

from modules.live_translate.tools.ai_service import AiService

ai_service = AiService()
