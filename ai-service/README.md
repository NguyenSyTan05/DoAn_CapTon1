# ClassBridge AI service (FastAPI, cổng 8000)

Bản sao của `FinalNCKH/be`, bổ sung **phòng theo phiên học** và **bộ STT mới**. Bản gốc không bị sửa.

## Chạy
```
cd finalDemo/ai-service
python -m uvicorn main:app --host 0.0.0.0 --port 8000
python -m pytest -q          # 112 test
```
Lần đầu cần có model Whisper small (Systran) và NLLB-200 trong cache Hugging Face.

## Phiên học (`?session=<session_id của Flask>`)
Mọi endpoint nhận `?session=`; không truyền thì dùng phòng mặc định chung (hành vi cũ).
Kho câu hỏi, câu trả lời, slide và WebSocket Q&A được tách theo phiên (`core/session_scope.py`).
`session` sai định dạng (`^[A-Za-z0-9_-]{1,64}$`) bị từ chối (REST 422, WebSocket đóng 1008).

## Dịch trực tiếp: `WS /api/v1/ws/live-translate`
| Tham số | Ý nghĩa |
|---|---|
| `session` | phòng |
| `role=lecturer` | gửi âm thanh (mặc định `viewer` khi có `session`) |
| `fmt=pcm32\|pcm16\|webm` | PCM float32/int16 16 kHz (nên dùng, qua AudioWorklet) hoặc WebM của MediaRecorder (cũ) |
| `lang=auto\|vi\|en` | ép ngôn ngữ để bỏ bước nhận diện ngôn ngữ (nhanh hơn) |
| `progressive=1` | `final` (lời gốc) gửi ngay, `translation` gửi sau; mặc định một tin gộp `result` |

Điều khiển từ giảng viên: `{"action":"set_language","language":"vi"}`, `{"action":"end"}`, `{"action":"ping"}`.
Người vào muộn (progressive) nhận `{"type":"history","items":[...]}` (50 dòng gần nhất).

## STT (`modules/live_translate`)
- `speech_engine.py`: `WhisperEngine` (faster-whisper). Chọn GPU bằng ctranslate2 và chạy thử thật; thiếu
  cuBLAS/cuDNN thì tự dùng CPU int8. Dùng model fine-tuned: đặt `WHISPER_MODEL_PATH=<thư mục CT2 có model.bin>`.
- `segmenter.py`: cắt câu theo khoảng lặng (ý tưởng từ tan-main), không gối đoạn nên không lặp từ.
- `text_filters.py`: làm sạch và lọc ảo giác. Câu ngắn ("yes", "thank you"...) chỉ bị chặn khi độ tin cậy thấp.

## Nguồn gốc (theo CLAUDE.md)
- Có sẵn: faster-whisper, NLLB-200, FastAPI; ý tưởng cắt câu theo ồn nền và bộ lọc ký tự lạ từ tan-main.
- Do nhóm điều chỉnh: phòng theo phiên, giao thức progressive, chọn thiết bị có kiểm tra thật, không gối đoạn.
- **Chưa có bằng chứng**: chưa đo WER/độ trễ trên giọng lớp học thật; ngưỡng RMS của segmenter chưa hiệu chỉnh.

## Giới hạn đã biết
- **Chưa xác thực**: ai biết `session_id` đều vào được phòng và gửi được âm thanh nếu khai `role=lecturer`.
  Bước tiếp theo: FastAPI hỏi Flask (`GET /auth/student/sessions/<id>`) với token để xác nhận quyền.
- Kho dữ liệu là in-memory, mất khi khởi động lại (chưa có database).
- Trên máy hiện tại GPU chưa dùng được (thiếu `cublas64_12.dll`), STT chạy CPU.
