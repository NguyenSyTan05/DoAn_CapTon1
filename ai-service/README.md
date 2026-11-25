# ClassBridge AI service (FastAPI, cổng 8000)

Bản sao của `FinalNCKH/be`, bổ sung **phòng theo phiên học** và **bộ STT mới**. Bản gốc không bị sửa.

## Chạy
```
cd finalDemo/ai-service
python -m uvicorn main:app --host 0.0.0.0 --port 8000
$env:AI_AUTH_MODE="off"; python -m pytest -q   # test hiện chạy ở chế độ off
```
Lần đầu cần có model Whisper small (Systran) và NLLB-200 trong cache Hugging Face.

## Phiên học (`?session=<session_id của Flask>`)
Mọi endpoint nhận `?session=`; không truyền thì dùng phòng mặc định chung (hành vi cũ — chỉ còn với
`AI_AUTH_MODE=off` và WebSocket; REST theo phòng ở `enforce` trả 422).
Kho câu hỏi, câu trả lời, slide và WebSocket Q&A được tách theo phiên (`core/session_scope.py`).
`session` sai định dạng (`^[A-Za-z0-9_-]{1,64}$`) bị từ chối (REST 422, WebSocket đóng 1008).

## Xác thực REST (`core/auth.py`, giai đoạn 1 — WebSocket chưa đổi)
| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `AI_AUTH_MODE` | `enforce` | `enforce`: bắt buộc JWT; `off`: bỏ qua mọi kiểm tra (chỉ dev/test, log cảnh báo khi khởi động) |
| `SECRET_KEY` | — | trùng `SECRET_KEY` của Flask, ≥ 32 ký tự khi `enforce` (thiếu/ngắn → không khởi động) |
| `FLASK_API_URL` | `http://127.0.0.1:5000` | Flask để hỏi quyền vào phòng |
| `AI_ALLOWED_ORIGINS` | `http://localhost:4000,http://127.0.0.1:4000` | CORS, phân tách bằng dấu phẩy |

ai-service không tự đọc file `.env`; đặt biến trong shell (xem `.env.example`).

- Header `Authorization: Bearer <token Flask>`. Token kiểm cục bộ bằng PyJWT: HS256, bắt buộc `exp`,
  `type == "access"`, `role` ∈ admin/giang_vien/sinh_vien. Sai → 401.
- Quyền vào phòng: `GET {FLASK_API_URL}/auth/sessions/<session>/access` một lần cho mỗi (token, phiên),
  nhớ 5 phút (từ chối/không có phiên nhớ 30 giây, không quá hạn token). Flask lỗi/không trả lời → 503.
- Ở `enforce`, route theo phòng mà không có `?session=` → 422.

| Route | Quyền |
|---|---|
| `POST /api/v1/questions` | sinh viên hoặc giảng viên của phiên |
| `GET /api/v1/questions`, `GET /api/v1/answers`, `GET /api/v1/slides/engagement\|file\|state` | mọi thành viên phiên (lecturer/student/admin) |
| `DELETE /api/v1/questions/{id}`, `POST /api/v1/answers`, `DELETE /api/v1/answers/{id}`, `POST /api/v1/slides/file`, `POST /api/v1/slides/event` | chỉ giảng viên của phiên |
| `POST /api/v1/translate`, `POST /api/v1/questions/aggregate` | token hợp lệ bất kỳ (không kiểm phòng) |
| `/healthz`, 3 WebSocket | chưa kiểm tra |

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
- **WebSocket chưa xác thực**: REST đã kiểm JWT + quyền phòng, nhưng ai biết `session_id` vẫn nghe được
  WebSocket và gửi được âm thanh nếu khai `role=lecturer` (giai đoạn 2).
- Quyền phòng được nhớ tối đa 5 phút: token bị thu hồi / sinh viên bị gỡ khỏi lớp vẫn còn quyền đến khi hết hạn cache.
- Kho dữ liệu là in-memory, mất khi khởi động lại (chưa có database).
- Trên máy hiện tại GPU chưa dùng được (thiếu `cublas64_12.dll`), STT chạy CPU.
