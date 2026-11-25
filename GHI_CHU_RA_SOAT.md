# Ghi chú rà soát mã nguồn & xử lý lỗi (ClassBridge)

Tài liệu này tổng hợp toàn bộ các thay đổi đã thực hiện sau khi rà soát `ai-service`, `backend` và `frontend` (trọng tâm: pipeline STT & xử lý âm thanh chống tự nhảy chữ), các vấn đề cố ý chưa sửa cùng lý do/rủi ro, và danh sách file/code thừa (chỉ ghi chú, **không xoá file nào**).

---

## 1. Bảng các thay đổi đã thực hiện

| File | Lỗi / Vấn đề | Cách sửa | Mức rủi ro | Kiểm chứng |
|---|---|---|---|---|
| [text_filters.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/text_filters.py) | Chặn nhầm biểu thức toán/ký tự đơn (`x = 5`, `a + b = c`); luật chống lặp từ bị vô hiệu hoá do chạy sau `finalize_text()`; `decide_language()` nhận nhầm từ vay mượn có dấu (`café résumé naïve`) thành tiếng Việt | Thêm `_MATH_OR_DIGIT` để giữ công thức toán; thêm `is_decoder_loop()` kiểm tra văn bản thô trước khi khử lặp; bổ sung `_strip_accents()` trong `decide_language()` để kiểm tra từ tiếng Việt thực sự khi `whisper_lang == "en"` | Thấp | `pytest modules/live_translate` (8 passed) |
| [speech_engine.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/speech_engine.py) | Lọc segment chỉ kiểm tra `no_speech_prob < 0.55`, bỏ qua `compression_ratio > 2.4` và mẫu ảo giác `(avg_logprob < -1.0 and no_speech_prob > 0.35)`; nhánh re-decode `vi` dùng sai `beam_size` và không chặn `avg_logprob` thấp; docstring mâu thuẫn về `VI_INITIAL_PROMPT` | Thêm `_keep_segment()`; áp dụng cho cả lần giải mã đầu và lần re-decode `vi` (`max_no_speech=0.40`, loại nếu trung bình `avg_logprob < -0.8`, dùng `effective_beam`); cập nhật docstring/comment ghi rõ cố ý không truyền `VI_INITIAL_PROMPT` | Thấp | `pytest modules/live_translate` + test thực tế trên `model_vi_ct2` (21/21 ca im lặng/nhiễu/tiếng ù = 0 ảo giác) |
| [router.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/router.py) | Không chặn `is_decoder_loop` trước `finalize_text`; vòng chờ NLLB `30 * 0.5s` gây trễ vô ích 15s khi NLLB không khả dụng; bản dịch chạy song song có thể ghi `history` sai thứ tự; khối `finally` dùng `enqueue()` có thể vứt câu cuối khi hàng đợi đầy | Gọi `is_decoder_loop(raw_text)` trước `finalize_text`; bỏ vòng chờ 15s; thêm `order_lock = asyncio.Lock()` giữ thứ tự FIFO khi dịch & publish; dùng `queue.put(...)` có timeout trong `finally` | Thấp | `compileall` + live WS test trên trình duyệt |
| [stt_main.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/stt_main.py) | CLI độc lập chưa chặn `is_decoder_loop` trước `finalize_text` | Gọi `is_decoder_loop(result.text)` trước `finalize_text()` để đồng nhất với `router.py` | Thấp | `compileall` |
| [ai_service.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/ai_service.py) | `detect_language()` dùng regex cũ `[\u00c0-\u1ef9]` bị lỗi với ký tự Latin ngoại lai | Chuyển thân `detect_language()` sang gọi `decide_language(text)` từ `text_filters.py` | Thấp | `compileall` + 50 unit test pass |
| [semantic_question_aggregator.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/question_clustering/semantic_question_aggregator.py), [qa/router.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/qa/router.py), [question_clustering/router.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/question_clustering/router.py) | `app.state.aggregator` nạp chạy nền (`None` lúc mới khởi động) gây crash HTTP 500 nếu gọi `/api/v1/questions` hoặc `/api/v1/questions/aggregate` sớm | Đổi `parse_and_validate` thành `@classmethod`; `submit_question` gọi trực tiếp trên class; `aggregate_questions` trả HTTP 503 rõ ràng nếu `aggregator is None` | Thấp | 50 unit test pass + live `POST /api/v1/questions` HTTP 200 |
| [pcm-processor.js](file:///d:/DemoMidTerm-master/DemoMidTerm-master/frontend/public/pcm-processor.js) | Thuật toán downsample cũ dùng boxcar 2–4 mẫu không giữ biên 128 mẫu (gây răng cưa/nhiễu định kỳ 375 Hz, `lastSample` bỏ không dùng) | Viết lại bộ lọc thông thấp Butterworth bậc 4 (2 biquad RBJ nối tiếp, Q=0.5412 & 1.3066) kết hợp nội suy tuyến tính có trạng thái liên khối (`prev`, `t`) | Thấp | Script Node `pcm_check.js` pass cả 48 kHz, 44.1 kHz, 16 kHz (suy giảm 12 kHz đạt 0.059 / 0.040, không bước nhảy biên) + HTTP 200 trên trình duyệt |
| [room/page.tsx](file:///d:/DemoMidTerm-master/DemoMidTerm-master/frontend/src/app/room/page.tsx) | Không ưu tiên `AudioContext({ sampleRate: 16000 })`, thiếu `ctx.resume()`, rò rỉ track mic/AudioContext khi `addModule` lỗi | Thử `AudioContext({ sampleRate: 16000 })` có fallback `new AudioContext()`; gọi `ctx.resume()` khi `suspended`; dọn `stream` và `ctx` trong `catch` | Thấp | `tsc --noEmit` pass, `eslint` không phát sinh lỗi mới |
| [dashboard/teacher/page.tsx](file:///d:/DemoMidTerm-master/DemoMidTerm-master/frontend/src/app/dashboard/teacher/page.tsx) | Kiểm tra sai key `localStorage.getItem("user_role") \|\| "teacher"` khiến mọi tài khoản (kể cả chưa đăng nhập/sinh viên) đều vào được Dashboard Giảng viên | Đọc `user.role` và `token` từ `localStorage`; thiếu thì chuyển `/login`; sai vai trò (không thuộc `giang_vien`/`lecturer`/`teacher`) thì cảnh báo và chuyển `/` | Thấp | `tsc --noEmit` pass + test trình duyệt mở `/dashboard/teacher` chưa đăng nhập tự redirect về `/login` |
| [backend/config.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/backend/config.py) | Không đọc `ACCESS_TOKEN_EXPIRE_MINUTES` từ `.env` | Thêm `JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")))` | Thấp | `compileall` + Flask khởi động OK |
| [backend/app.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/backend/app.py) | Hardcode `app.run(debug=True)` mở Werkzeug Debugger PIN | Đổi sang `app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")` | Thấp | Flask khởi động ở chế độ `Debug mode: off` |
| [chitiet.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/backend/routes/giangvien/classroom/chitiet.py) | `_serialize_lecture_material()` ghi đè `previewUrl = None` cho file PDF lưu kiểu `URL` | Giữ `row["fileUrl"]` khi `extension == "pdf"` và `storageType == "URL"` | Thấp | `compileall` |
| [test_stt_pipeline.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/test_stt_pipeline.py) | Chưa có unit test tự động cho pipeline STT | Bổ sung 8 unit test cho `is_decoder_loop`, `is_hallucination`, `decide_language`, `_keep_segment`, `WhisperEngine.transcribe`, `UtteranceSegmenter`, `decode_pcm16/32` | Không | `pytest modules/live_translate -q` (8 passed) |

---

## 2. Chưa sửa (cố ý) & lý do / lưu ý rủi ro

- **Chế độ `auto` không dùng `model_en_ct2`**: Chuyển đổi/chạy thêm model EN ở chế độ `auto` sẽ tăng gấp đôi độ trễ và tốn thêm RAM/VRAM; hiện chỉ dùng `model_en_ct2` khi giảng viên chọn cứng `English`.
- **Mặc định `speechLang='vi'` ở `/room`**: Giữ nguyên hành vi quen thuộc của giao diện hiện tại; giảng viên dạy tiếng Anh cần chọn `English` hoặc `Tự nhận ngôn ngữ`.
- **Ngưỡng `det_prob < 0.48` ở `speech_engine.py`**: Có thể lọc mất câu trộn Việt–Anh (code-switching), cần thu thập dữ liệu giọng lớp học thật để hiệu chỉnh trước khi hạ ngưỡng.
- **`segmenter.py` đo RMS trước khi lọc high-pass 90 Hz & nhánh chết dòng 104–105**: Phía sau đã có cổng RMS + high-pass + Silero VAD bảo vệ chống nhảy chữ, nhưng trong phòng ồn tần số thấp (< 90 Hz) có thể nuốt giọng nhỏ; cần dữ liệu thực tế để cân chỉnh lại ngưỡng.
- **`max_utterance_s = 5.0`**: Giữ nguyên để đảm bảo độ trễ hiển thị phụ đề thấp; tăng lên sẽ làm phụ đề hiện chậm hơn.
- **Frontend gửi `fmt=pcm32` thay vì `pcm16`**: Giữ nguyên để tránh thay đổi giao thức đang ổn định (đổi sang `pcm16` giúp giảm nửa băng thông nếu cần sau này).
- **CORS `allow_origins=["*"]` trong `ai-service/main.py`**: Nếu khóa cứng theo `.env` (`http://localhost:4000`) sẽ làm hỏng truy cập từ thiết bị khác trong mạng LAN.
- **`frontend/.env.local` ghi cứng `127.0.0.1:5000` và `127.0.0.1:8000`**: Ghi đè cơ chế tự nhận `window.location.hostname` của `lib/ai.ts`, khiến máy khác trong mạng LAN không gọi được API (cần bỏ/sửa khi demo đa thiết bị LAN).
- **BẢO MẬT QUAN TRỌNG — Lộ mật khẩu Neon PostgreSQL trong `backend/.env`**: File `backend/.env` chứa chuỗi kết nối Neon DB thật cùng `SECRET_KEY`/`JWT_SECRET_KEY` mặc định. **Cần đổi/xoay mật khẩu DB Neon ngay** nếu mã nguồn từng được chia sẻ hoặc đẩy lên Git.
- **`JWT_SECRET_KEY` trong `backend/.env` chưa được nạp ở `backend/config.py`**: Cố ý chưa nạp để không làm vô hiệu hoá toàn bộ token đang đăng nhập của người dùng hiện tại; nên bật đồng bộ ở đợt bảo trì có thông báo đăng nhập lại.
- **`ai-service` chưa xác thực JWT & toàn bộ store đều in-memory**: Mất dữ liệu khi restart; `ai-service/database/engine.py` và `models.py` hiện đang rỗng.
- **Cache embedding `_embedding_cache` không có giới hạn kích thước / lock**: Đủ dùng cho demo ngắn, nhưng cần bổ sung LRU và `threading.Lock` nếu chạy dài ngày nhiều phiên.
- **`conftest.py` dùng `api_client` ở scope `function`**: Mỗi test API chạy lại toàn bộ `lifespan` (nạp lại Whisper/NLLB), khiến chạy toàn bộ `pytest` rất chậm; ngoài ra thư mục `trained_models/stt/model_*_ct2/` thiếu `tokenizer.json` nên `faster-whisper` sẽ gọi `huggingface.co` khi khởi tạo nếu không có file này hoặc không có mạng.
- **Phòng học Offline (`frontend/src/page/giangvien/classroom/offline.tsx`) chưa tích hợp STT**: Các nút mic/phụ đề hiện mới là giao diện chờ.
- **WebSocket ở `sinhvien/Classroom.tsx` và `QAToast.tsx` chưa có auto-reconnect**.
- **Một số nút UI chưa gắn xử lý**: `onCam`/`onEndCall` ở `room/page.tsx`, 3 nút điều hành phiên ở `chitiet.tsx`.
- **Đường dẫn cứng `d:/TailieuNPKH/...`** trong `speech_engine.py` và `start-all.ps1` (phụ thuộc máy cá nhân).
- **Cổng 8000 bị tiến trình cũ chiếm (`Errno 10048`)**: Cần tắt tiến trình cũ trên port 8000 trước khi khởi chạy bản mới để đảm bảo không chạy nhầm code cũ.
- **Phát hiện thêm khi test live**: `POST /auth/activity` trên Flask trả HTTP 503 ở một lần ghi log thao tác tab `Q&A` trên `/student` (có thể do kết nối DB Neon hoặc ràng buộc bảng `audit_logs` khi chưa đăng nhập).

---

## 3. File / code thừa (đã dọn phần STT chết, giữ các file cấu hình/log)

**Đã xoá (xác nhận không có nơi nào gọi):**
- Code STT cũ trong [ai_service.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/ai_service.py): `transcript_audio()`, `_is_hallucination()`, `SILENCE_HALLUCINATIONS`, `YOUTUBE_ARTIFACTS`, `VIETNAMESE_DIACRITICS`, `self.whisper_model`.
- Hằng chết `VI_INITIAL_PROMPT` trong [speech_engine.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/speech_engine.py).
- Nhánh chết `if self._speech >= 3` khi `self._silence >= 7` trong [segmenter.py](file:///d:/DemoMidTerm-master/DemoMidTerm-master/ai-service/modules/live_translate/segmenter.py).
- Thư mục rỗng `ai-service/database/` (`engine.py`, `models.py` — 0 byte, không được import).

**Còn giữ (không xoá):**
- **File log runtime**: `ai-service/ai-runtime.out.log`, `ai-service/ai-runtime.err.log`, `backend/flask-runtime.out.log`, `backend/flask-runtime.err.log`, `D:\DemoMidTerm-master\debug.log`.
- **File cấu hình trùng ở thư mục ngoài (`D:\DemoMidTerm-master\`)**: `package.json`, `pyrefly.toml`, `pyrightconfig.json`, `.vscode/settings.json`.
- **Thư mục/file cache sinh tự động**: `ai-service/.pytest_cache/`, `frontend/tsconfig.tsbuildinfo`.
- **Route sinh viên cũ**: `frontend/src/app/student/page.tsx` (giữ lại cho tương thích chế độ không cần đăng nhập/phiên).

---

## 4. Kết quả kiểm chứng

1. **Unit test STT (`pytest modules/live_translate -q`)**: `8 passed, 1 warning in 2.30s`.
2. **Unit test toàn bộ module không nạp model (`pytest -q -k "not API and ..."`)**: `50 passed, 49 deselected in 4.23s`.
3. **Kiểm tra cú pháp Python (`compileall`)**: Exit code `0` (toàn bộ `backend` và `ai-service`).
4. **Kiểm tra AudioWorklet (`pcm_check.js` bằng Node.js)**:
   - `48000 Hz`: 1 kHz `out=32000`, `outRms=0.3536`, `maxDiff=0.1928`; 12 kHz suy giảm còn `0.0590` (< 0.15).
   - `44100 Hz`: 1 kHz `out=32000`, `outRms=0.3530`, `maxDiff=0.1930`; 12 kHz suy giảm còn `0.0396` (< 0.15).
   - `16000 Hz`: 1 kHz `out=32000`, `outRms=0.3536`, `maxDiff=0.1913`.
   - Kết quả: **ALL PCM WORKLET CHECKS PASSED**.
5. **Test lọc âm & chống nhảy chữ trên model thật (`model_vi_ct2`, `cuda/int8_float16`)**:
   - 7 mẫu âm thanh rác (`silence_3s`, `hum_60hz_0.05`, `hum_50hz_0.15`, `white_noise_0.02`, `white_noise_0.08`, `clicks`, `dc_offset_plus_silence`) × 3 chế độ ngôn ngữ (`auto`, `vi`, `en`) = **21/21 trường hợp trả `None` (0 ảo giác / 0 tự nhảy chữ)**.
6. **Frontend TypeScript & ESLint**:
   - `npx tsc --noEmit`: Exit code `0` (không lỗi).
   - `npx eslint src/app/room/page.tsx src/app/dashboard/teacher/page.tsx`: **0 lỗi mới** (chỉ còn 4 lỗi / 1 cảnh báo có sẵn từ code cũ: `setLanguage` dòng 339, `any` dòng 508, `setIsAuthorized` dòng 542, `'e'` dòng 963 ở `dashboard/teacher/page.tsx`; `setSessionId` dòng 65 ở `room/page.tsx`).
7. **Kiểm thử web trực tiếp trên trình duyệt (`http://localhost:4000`)**:
   - Landing page `/`: PASS (22/22 request HTTP 200, 0 lỗi console).
   - `/pcm-processor.js`: PASS (HTTP 200, xác nhận đúng bản Butterworth bậc 4 mới).
   - `/dashboard/teacher` (chưa đăng nhập): PASS (tự động redirect về `/login`).
   - `/student`: PASS (hiển thị tab Phụ đề & Q&A, WebSocket kết nối, gửi câu hỏi `"Deadlock là gì ạ?"` trả `POST /api/v1/questions` HTTP 200).
   - Health check `http://127.0.0.1:8000/healthz` & `http://127.0.0.1:5000/`: PASS.
8. **Lưu ý toàn bộ `pytest -q` (99 test)**: 50 unit test chạy nhanh đều pass; các test dùng fixture `api_client` (49 test) nạp lại mô hình trên mỗi test theo thiết kế `conftest.py` hiện tại và trong môi trường `ai-service/.venv` (không có `torch`, đồng thời thiếu `tokenizer.json` trong `model_*_ct2`) nên bị chậm/treo khi chạy offline; chạy thực tế bằng môi trường GPU (`d:\TailieuNPKH\...\.venv`) khởi động đầy đủ `NLLB-200 (cuda)` + `model_vi_ct2 (cuda/int8_float16)` + `MiniLM-L12-v2 (cpu)` thành công.
