# Ghi chú các file STT (Speech-to-Text) trong `ai-service`

Tài liệu này ghi lại rõ **file/model gốc của bạn**, **file mới thêm**, và **file đã tối ưu/cập nhật** khi tích hợp module STT vào `DemoMidTerm-master/ai-service`.

---

## 1. Các file & model của bạn (chuyển từ repo cá nhân `NguyenSyTan05`)

| Thành phần | Đường dẫn trong `ai-service` | Nguồn gốc từ repo cá nhân | Ghi chú |
|---|---|---|---|
| **Model STT Tiếng Việt (CT2)** | `trained_models/stt/model_vi_ct2/` | `whisper-decoder-micro1-ct2/` (`01_TRAIN_TIENG_VIET/model_vi_ct2/`) | Model Whisper CTranslate2 đã fine-tune cho tiếng Việt (`model.bin`, `config.json`, `preprocessor_config.json`, `vocabulary.json`) |
| **Model STT Tiếng Anh (CT2)** | `trained_models/stt/model_en_ct2/` | `02_TRAIN_TIENG_ANH/model_en_ct2/` | Model Whisper CTranslate2 đã fine-tune cho tiếng Anh & accent (`model.bin`, `config.json`, `preprocessor_config.json`, `vocabulary.json`) |
| **Lõi logic STT & Prompt** | `modules/live_translate/speech_engine.py` | `unified_speech_recognizer.py` | Chứa `VI_INITIAL_PROMPT` 5 dấu thanh, `beam_size=2`, `temperature=0.0`, `repetition_penalty=1.2`, `no_repeat_ngram_size=3`, Silero VAD `speech_pad_ms=400` |
| **Bộ lọc văn bản & chống ảo giác** | `modules/live_translate/text_filters.py` | `unified_speech_recognizer.py` | Chứa `clean_transcript_text`, `remove_repeated_phrases`, `is_hallucination`, `decide_language`, chặn ký tự ngoại lai & câu rác YouTube |
| **Cắt câu theo khoảng lặng** | `modules/live_translate/segmenter.py` | `main.py::ws_stream` (`tan-main`) | Ý tưởng ngưỡng ồn nền thích nghi + pre-roll + cắt câu theo khoảng lặng |

---

## 2. Các file mới thêm

| Đường dẫn | Mục đích |
|---|---|
| `trained_models/stt/model_vi_ct2/` | Thư mục mới chứa bản copy model STT Tiếng Việt đã train (độc lập với ổ `d:\TailieuNPKH\...`) |
| `trained_models/stt/model_en_ct2/` | Thư mục mới chứa bản copy model STT Tiếng Anh đã train |
| `stt_main.py` | File `main` chạy xử lý âm thanh & STT độc lập (CLI + hàm `process_audio_pcm` / `process_audio_file`), dùng chung pipeline với FastAPI server |
| `README_STT.md` | File ghi chú phân loại file của bạn và file mới thêm |

---

## 3. Các file đã tối ưu / cập nhật

| Đường dẫn | Nội dung tối ưu |
|---|---|
| `modules/live_translate/audio_utils.py` | Tách helper `_segment_to_pcm32`, thêm `decode_pcm16`, `decode_pcm32`, `load_audio_file`, và `preprocess_audio_for_stt` (khử NaN/DC offset, chuẩn hóa âm lượng giọng nhỏ mà không khuếch đại khoảng lặng) |
| `modules/live_translate/speech_engine.py` | Hỗ trợ nạp **2 model đã train** (`model_vi_ct2` cho `vi`/`auto`, `model_en_ct2` nạp lười khi dùng `en` để tiết kiệm RAM trên máy 8GB), bỏ qua khoảng lặng sớm trước khi suy luận, dọn bộ nhớ khi lỗi CUDA trước khi lùi về `cpu/int8` |
| `modules/live_translate/text_filters.py` | Bổ sung đầy đủ các mẫu ảo giác từ `unified_speech_recognizer.py`: chặn ảo giác tiếng Anh khi ép `lang="vi"`, chặn từ Latin/Romance ngoại lai ở chế độ `auto`, mở rộng danh sách rác YouTube |
| `modules/live_translate/router.py` | Dùng `decode_pcm16`/`decode_pcm32` từ `audio_utils.py` (không lặp code) và truyền `forced_lang`, `detected_lang` vào `is_hallucination()` |
| `.env` | Trỏ `WHISPER_MODEL_PATH`, `WHISPER_VI_MODEL_PATH`, `WHISPER_EN_MODEL_PATH` về `trained_models/stt/...` ngay bên trong `ai-service` |

---

## 4. Rà soát lần 2 (sửa lỗi phát hiện khi test mọi trường hợp)

| File | Lỗi phát hiện | Đã sửa |
|---|---|---|
| `text_filters.py` | Dải `[À-ỹ]` coi cả chữ Hy Lạp/Ấn Độ, `ñ`, `ü`... là tiếng Việt | Dùng đúng bảng ký tự có dấu tiếng Việt |
| `text_filters.py` | Luật lặp ký tự chặn nhầm số `100000` | Chỉ xét chữ cái (`hmmmmm` vẫn bị chặn) |
| `text_filters.py` | Ở `lang="vi"`, câu tự tin như `"Ok"`, `"Yes"` bị chặn tuyệt đối | Chỉ chặn tuyệt đối các câu "học vẹt" (`I see the light`, `I'm coming`...), còn `ok/yes` xét theo độ tin cậy |
| `text_filters.py` | `non è` lọt lưới vì `è` bị coi là dấu Việt; nháy cong `I’m` không khớp; `big, big way` không khớp | Dùng ký tự riêng của tiếng Việt, đổi `’`→`'`, chuẩn hóa khoảng trắng |
| `audio_utils.py` | Truyền mảng `int16` hoặc stereo vào sẽ thành tín hiệu ±1 (rác) | Tự chuẩn hóa `int16/int32`, gộp stereo → mono |
| `speech_engine.py` | Nạp lười model EN khi RAM gần cạn có thể làm crash cả server (`mkl_malloc`/`access violation`) | Kiểm tra RAM trống (`WHISPER_EN_MIN_FREE_MB`, mặc định 700 MB); thiếu thì tạm dùng model VI và thử lại sau |
| `segmenter.py` | Một tiếng click/gõ bàn 50 ms cũng bị gửi đi nhận dạng | Cần ≥ 200 ms lời nói mới tạo câu |
| `stt_main.py` | Tiền xử lý 2 lần; file không tồn tại/hỏng ném traceback | Bỏ lặp; trả mã lỗi `2` (không có file) / `3` (file hỏng) |

**Kết quả test (61/61 trường hợp đạt, file test tạm đã xóa):** giải mã gói lỗi/lẻ byte/NaN, im lặng, nhiễu trắng, giọng nhỏ, DC offset, stereo/int16, câu rất ngắn, click, nói liền 25 s, chữ ngoại lai, câu rác YouTube, gọi đồng thời 3 luồng, CLI lỗi file, và giọng nói thật:

| Model | Âm thanh | Kết quả |
|---|---|---|
| `model_vi_ct2` | "Xin chào các em. Hôm nay chúng ta sẽ học về hệ điều hành và bế tắc." | `Xin chào các em.` / `Hôm nay chúng ta sẽ học về hệ điều hình và bế tắc.` |
| `model_en_ct2` | "Good morning everyone. Today we will learn about operating systems and deadlock." | `Good morning everyone.` / `Today we will learn about operating systems and dead luck.` |

> Lỗi `hình`/`dead luck` là độ chính xác của model (giọng TTS máy), không phải lỗi code. Chưa đo WER trên giọng lớp học thật.

---

## 5. Cách chạy thử nhanh `stt_main.py`

```powershell
cd D:\DemoMidTerm-master\DemoMidTerm-master\ai-service
.\.venv\Scripts\python.exe stt_main.py --audio path\to\audio.wav --lang auto
```

---

## 6. Rà soát lần 3 (chống tự nhảy chữ)

Chi tiết toàn bộ rà soát, rủi ro, các mục chưa sửa và file thừa xem tại [GHI_CHU_RA_SOAT.md](../GHI_CHU_RA_SOAT.md).

| File | Nội dung tối ưu / sửa lỗi |
|---|---|
| `modules/live_translate/text_filters.py` | Thêm `is_decoder_loop()` chặn vòng lặp decoder trên văn bản thô trước khi khử lặp; giữ biểu thức toán/số (`x = 5`, `a + b = c`); sửa `decide_language()` dùng `_strip_accents()` để không nhận nhầm từ vay mượn (`café`, `naïve`) thành tiếng Việt |
| `modules/live_translate/speech_engine.py` | Thêm `_keep_segment()` chặn `compression_ratio > 2.4` và mẫu ảo giác `(avg_logprob < -1.0, no_speech_prob > 0.35)`; siết nhánh re-decode `vi` (`max_no_speech=0.40`, bỏ nếu `avg_logprob < -0.8`, đồng bộ `effective_beam`); làm rõ ghi chú cố ý không dùng `VI_INITIAL_PROMPT` |
| `modules/live_translate/router.py` & `stt_main.py` | Gọi `is_decoder_loop()` trước `finalize_text()`; bỏ vòng chờ NLLB 15s; thêm `order_lock` giữ thứ tự FIFO cho bản dịch/`history`; dùng `queue.put()` trong `finally` tránh mất câu cuối |
| `modules/live_translate/ai_service.py` | Chuyển `detect_language()` sang dùng chung `text_filters.decide_language()` |
| `frontend/public/pcm-processor.js` & `frontend/src/app/room/page.tsx` | Nâng cấp downsample sang bộ lọc thông thấp Butterworth bậc 4 + nội suy tuyến tính giữ trạng thái liên khối; ưu tiên `AudioContext({ sampleRate: 16000 })`, gọi `ctx.resume()` và dọn mic/AudioContext khi lỗi |
| `modules/live_translate/test_stt_pipeline.py` | Thêm 8 unit test cho pipeline STT & giải mã PCM; kiểm tra thực tế trên `model_vi_ct2` (21/21 mẫu im lặng/nhiễu/tiếng ù = 0 ảo giác) |

---

## 7. Rà soát lần 4 (tăng tốc thời gian thực, bắt trọn câu & sửa chế độ Auto song ngữ)

| File | Nguyên nhân cũ | Đã tối ưu |
|---|---|---|
| `frontend/src/app/room/page.tsx` | `autoGainControl: false` làm tín hiệu micro laptop nhỏ, khiến segmenter cắt vụn câu thành đoạn `1.1s` | Bật lại `autoGainControl: true` kết hợp `noiseSuppression` & `echoCancellation` |
| `modules/live_translate/segmenter.py` | `max_utterance_s=8.0` + chờ lặng `500–600ms` gây trễ cao; ngưỡng duy trì `0.011` quá cao làm ngắt giữa câu | Giảm `max_utterance_s=4.5s`, chờ lặng `400ms`, thêm `pre_roll=400ms`, lọc thông cao bậc 4 `110 Hz` + hysteresis duy trì `0.006` |
| `modules/live_translate/audio_utils.py` | `is_high_freq_noise > 0.45` loại nhầm âm xuýt (`s/x/ch/th`); ngưỡng khuếch đại `0.012` bỏ sót giọng nói nhỏ | Chỉ coi là nhiễu rít khi thiếu năng lượng formant `120–3500 Hz`; chuẩn hóa giọng nhỏ từ `rms >= 0.005` (`max_gain=4.0`) |
| `modules/live_translate/speech_engine.py` | `beam_size=5` chậm; chế độ `auto` dùng `model_vi_ct2` đọc tiếng Anh và bỏ câu có `det_prob < 0.48`; `no_speech < 0.45` & `logprob < -1.0` loại nhầm câu thật | Đưa `beam_size=2` trên CUDA; nạp sẵn cả `model_vi_ct2` + `model_en_ct2` lên VRAM; ở chế độ `auto` dùng `detect_language()` so sánh xác suất `vi` vs `en` để định tuyến thẳng sang đúng model chuyên biệt |
| `modules/live_translate/router.py` | `MAX_QUEUE = 2` làm rớt câu khi giảng viên nói nhiều mệnh đề liên tiếp | Nâng `MAX_QUEUE = 8` theo đúng thiết kế kiến trúc ClassBridge |
