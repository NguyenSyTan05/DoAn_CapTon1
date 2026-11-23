# ClassBridge — Hệ thống hỗ trợ lớp học song ngữ Anh–Việt (EMI)

Giảng viên nói → hệ thống nhận dạng giọng nói (STT), dịch Anh ↔ Việt và phát **phụ đề trực tiếp** cho sinh viên; đồng thời **chia sẻ slide** và thu thập **câu hỏi ẩn danh** để gom nhóm cho giảng viên.

Tài liệu chi tiết luồng đi của từng tính năng: [`docs/LuongSuKien_ClassBridge.docx`](docs/LuongSuKien_ClassBridge.docx).

---

## 1. Kiến trúc

| Thành phần | Thư mục | Công nghệ | Cổng |
|---|---|---|---|
| Frontend | `frontend/` | Next.js 16, React 19, TypeScript | **4000** |
| Backend tài khoản & lớp học | `backend/` | Flask, JWT, SQLAlchemy, PostgreSQL (Neon) | **5000** |
| Backend AI thời gian thực | `ai-service/` | FastAPI, faster-whisper (STT), NLLB-200 (dịch), MiniLM (gom nhóm) | **8000** |

```
Trình duyệt (Next.js :4000)
   ├── REST + JWT ──────────────► Flask :5000 ──► PostgreSQL (tài khoản, lớp, phiên, thành viên, chat, audit)
   └── REST + WebSocket ────────► FastAPI :8000   (phụ đề, hỏi đáp, slide — theo ?session=<session_id>, lưu trong RAM)
```

`session_id` (UUID của bảng `sessions` ở Flask) là chìa khóa nối hai backend: Flask biết ai thuộc lớp nào; FastAPI dùng nó để tách dữ liệu giữa các phòng học.

### Tính năng chính
- Đăng ký sinh viên 3 bước (xác thực email), đăng nhập theo vai trò (sinh viên / giảng viên / quản trị).
- Giảng viên tạo lớp → hệ thống sinh sẵn các phiên học theo lịch và **mã lớp**.
- Sinh viên nhập mã lớp để tham gia; vào **phòng chờ** nếu giảng viên chưa bắt đầu.
- Phòng học `/room`: phụ đề song ngữ trực tiếp, slide PDF đồng bộ trang, hỏi đáp ẩn danh, popup câu trả lời.
- Dashboard giảng viên: gom nhóm câu hỏi theo ngữ nghĩa, trả lời, biểu đồ tương tác theo slide.
- Trang quản trị: tài khoản, lớp, nhật ký hoạt động, thống kê tương tác.

---

## 2. Cấu trúc thư mục

```
finalDemo/
├── backend/        Flask API (app.py, routes/, migrations/, requirements.txt, .env.example)
├── ai-service/     FastAPI AI (main.py, modules/, core/, README.md, requirements.txt)
├── frontend/       Next.js (src/app, src/page, src/components, src/lib, src/services)
├── docs/           Tài liệu luồng sự kiện (.docx)
├── db.sql          Lược đồ cơ sở dữ liệu đầy đủ (PostgreSQL 15+)
└── frontend_vite_backup/   Bản frontend Vite cũ (chỉ để đối chiếu cục bộ, đã nằm trong .gitignore)
```

---

## 3. Yêu cầu

- **Python 3.11** (không dùng 3.13+ vì một số thư viện AI chưa hỗ trợ).
- **Node.js 20+** và npm.
- **PostgreSQL** (nhóm dùng chung một cơ sở dữ liệu Neon — xem mục 4.1).
- Dung lượng trống vài GB: lần chạy AI đầu tiên tải model Whisper small, NLLB-200 (600M) và MiniLM.
- (Tuỳ chọn) GPU NVIDIA có CUDA 12 + cuBLAS/cuDNN để STT nhanh hơn. Không có thì tự chạy CPU.
- Trình duyệt **Chrome hoặc Edge** (cần micro và AudioWorklet).

---

## 4. Cài đặt và cấu hình

### 4.1. Cơ sở dữ liệu
**Cách A (khuyến nghị): dùng chung DB của nhóm.** Xin trưởng nhóm chuỗi `DATABASE_URL` qua kênh riêng (không gửi trong chat công khai, không commit lên GitHub).

**Cách B: tự tạo DB mới** (PostgreSQL 15+): chạy `db.sql`, rồi lần lượt các file trong `backend/migrations/` (`001` → `004`; bỏ qua lỗi “đã tồn tại” nếu có). Sau đó tạo tài khoản giảng viên theo mục 6.3.

### 4.2. Backend Flask (`backend/`)
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # rồi điền giá trị vào .env
```
Các biến trong `backend/.env` (xem `.env.example`):

| Biến | Ý nghĩa |
|---|---|
| `DATABASE_URL` | Chuỗi kết nối. **Phải dùng** `postgresql://…` hoặc `postgresql+psycopg2://…` (không dùng `+asyncpg`). |
| `SECRET_KEY` | Khóa ký JWT, đặt chuỗi dài ngẫu nhiên. |
| `FRONTEND_ORIGIN` | **Phải là `http://localhost:4000`** (mặc định của code là 5173 nên nếu quên sẽ bị lỗi CORS). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Gửi email xác thực khi đăng ký (xem `backend/SMTP_SETUP.md`). |
| `EMAIL_VALIDATION_API_KEY` | Kiểm tra email có thật (xem `backend/EMAIL_VALIDATION.md`). |

> Chỉ **đăng ký sinh viên** mới cần SMTP và `EMAIL_VALIDATION_API_KEY`. Đăng nhập bằng tài khoản có sẵn thì không cần.

### 4.3. AI service FastAPI (`ai-service/`)
```powershell
cd ai-service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Không bắt buộc cấu hình. Tuỳ chọn: `WHISPER_MODEL_PATH=<thư mục model Whisper CT2>` để dùng model đã fine-tune thay cho `small` mặc định. Chi tiết: `ai-service/README.md`.

> Nếu cài `hdbscan` lỗi trên Windows, cài *Microsoft C++ Build Tools* hoặc tìm bản wheel phù hợp với Python 3.11.

### 4.4. Frontend Next.js (`frontend/`)
```powershell
cd frontend
npm install
copy .env.example .env.local
```
`frontend/.env.local` (đều có mặc định, chỉ chỉnh khi cần):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:5000` | Địa chỉ Flask |
| `NEXT_PUBLIC_AI_URL` | `http://<host-đang-mở>:8000` | Địa chỉ FastAPI AI |

---

## 5. Chạy hệ thống

Mở **3 cửa sổ terminal** (đã kích hoạt `.venv` ở hai terminal Python):

```powershell
# Terminal 1 — Flask (cổng 5000)
cd backend
python app.py

# Terminal 2 — AI (cổng 8000). Lần đầu tải model nên chờ vài phút
cd ai-service
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 3 — Frontend (cổng 4000)
cd frontend
npm run dev
```

Kiểm tra nhanh:
- Flask: <http://127.0.0.1:5000/> → `ClassBridge Backend is running`
- AI: <http://localhost:8000/healthz> → `{"status":"ok"}`
- Giao diện: **<http://localhost:4000>**

> ⚠️ Mở giao diện bằng **`localhost`**, không dùng `127.0.0.1` (chế độ dev của Next.js chặn nguồn lạ nên trang sẽ không tương tác được).

---

## 6. Tài khoản test

### 6.1. Giảng viên (dùng chung để test)

| | |
|---|---|
| Email | `teacher@gmail.com` |
| Mật khẩu | `Teacher123@` |
| Vai trò | Giảng viên (mã `GV-TEACHER01`) |

> Tài khoản này nằm trong **cơ sở dữ liệu dùng chung của nhóm**. Chỉ dùng để test; không dùng mật khẩu này ở nơi khác. Nếu repo công khai, hãy đổi mật khẩu sau khi demo xong.

### 6.2. Sinh viên
- Tự đăng ký tại `/register` (3 bước, cần cấu hình SMTP ở mục 4.2), **hoặc**
- Tạo trực tiếp trong DB theo mục 6.3.

### 6.3. Tự tạo tài khoản trực tiếp trong DB (khi dùng DB mới hoặc chưa có SMTP)
Tạo mã băm mật khẩu:
```powershell
cd backend
python -c "from werkzeug.security import generate_password_hash as g; print(g('MatKhauCuaBan1!'))"
```
Rồi chạy SQL (thay `<HASH>`):
```sql
-- Giảng viên
INSERT INTO lecturers (lecturer_code, full_name, email, password_hash)
VALUES ('GV-TEST01', 'Giảng viên Test', 'gv.test@example.com', '<HASH>');

-- Sinh viên (MSSV đúng 11 chữ số)
INSERT INTO students (student_code, full_name, email, password_hash)
VALUES ('12345678901', 'Sinh viên Test', 'sv.test@example.com', '<HASH>');
```
Mật khẩu nên có chữ hoa, chữ thường, số và ký tự đặc biệt.

---

## 7. Kịch bản test end-to-end (làm theo thứ tự)

> Dùng **hai trình duyệt khác nhau** (hoặc Chrome thường + cửa sổ ẩn danh): đăng nhập lưu ở `localStorage` nên hai tài khoản trong cùng một trình duyệt sẽ ghi đè lẫn nhau. Giao diện có nhãn “Giảng viên: …” / “Sinh viên: …” để nhận biết.

1. **Giảng viên** (trình duyệt 1): vào `http://localhost:4000/login`, đăng nhập `teacher@gmail.com`. Vào **My Classes** (`/giangvien/classes`) → tạo lớp mới, **chọn lịch có buổi hôm nay**. Sao chép **mã lớp** (dạng `MÃMÔN-1A2B3C4D`).
2. **Sinh viên** (trình duyệt 2): đăng nhập (hoặc đăng ký). Ở `/sinhvien` bấm **Nhập mã lớp**, dán mã → được đưa vào **phòng chờ** (banner vàng).
3. **Giảng viên:** vào **Classroom** (`/giangvien/classroom`) → mở phiên hôm nay → bấm **Học online** (hoặc offline) để chuyển phiên sang `LIVE` → bấm **Mở phòng AI (phụ đề song ngữ)** (mở `/room?session=…`).
4. **Sinh viên:** trong vài giây phòng chờ tự chuyển sang **Trực tiếp**.
5. **Phụ đề:** giảng viên bấm nút **Mic một lần**, cho phép trình duyệt dùng micro, rồi nói. Sinh viên thấy lời gốc xuất hiện trước, bản dịch xuất hiện sau (cột EN/VI).
6. **Slide:** giảng viên bấm **Upload PDF**, chọn file, bấm Next/Prev. Sinh viên thấy slide tự chuyển theo.
7. **Hỏi đáp:** sinh viên gõ câu hỏi ở khung chat. Giảng viên bấm **Mở Dashboard Giảng Viên** → thấy nhóm câu hỏi → nhập câu trả lời → sinh viên nhận popup.
8. **Kết thúc:** giảng viên bấm **Kết thúc phiên học** ở trang chi tiết phiên.

Mỗi bước chi tiết (API nào được gọi, dữ liệu ghi ở đâu) có trong `docs/LuongSuKien_ClassBridge.docx`.

---

## 8. Kiểm thử tự động

```powershell
cd ai-service
python -m pytest -q          # khoảng 2 phút (nạp model thật), kỳ vọng: 117 passed
```
Backend Flask và frontend hiện chưa có bộ test tự động; kiểm tra frontend bằng `npm run build` (có kiểm tra TypeScript).

---

## 9. Xử lý sự cố thường gặp

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| Flask báo `Either 'SQLALCHEMY_DATABASE_URI' … must be set` | Chưa có `backend/.env` hoặc thiếu `DATABASE_URL`. |
| Flask lỗi kết nối/`asyncpg` | `DATABASE_URL` đang dùng `postgresql+asyncpg://`. Đổi thành `postgresql+psycopg2://`. |
| Trình duyệt báo CORS khi đăng nhập | `FRONTEND_ORIGIN` trong `backend/.env` chưa là `http://localhost:4000`, hoặc chưa khởi động lại Flask sau khi sửa. |
| Trang không bấm được / nút không phản hồi | Đang mở bằng `127.0.0.1`. Dùng `http://localhost:4000`. |
| Đăng ký sinh viên báo lỗi ở bước 2 | Thiếu cấu hình SMTP hoặc `EMAIL_VALIDATION_API_KEY`. |
| Bấm Mic không có phụ đề | Trình duyệt chặn micro (kiểm tra biểu tượng ổ khóa); AI service chưa chạy hoặc đang tải model; nút Mic phải ở trạng thái “đang bật” sau khi bấm. |
| Phụ đề trễ vài giây | Bình thường khi chạy CPU. Có GPU + cuBLAS sẽ nhanh hơn. Log AI có dòng `không dùng được cuda/float16` là hệ thống tự lùi về CPU. |
| Sinh viên không thấy slide đổi trang / dữ liệu lẫn lộn | Có hai tiến trình cùng nghe cổng 8000. Tắt hết rồi chạy lại một AI service duy nhất. |
| Thấy nút “Mute All”, “Dashboard Giảng Viên” khi đang là sinh viên | Trình duyệt đang đăng nhập bằng tài khoản giảng viên (dùng chung `localStorage`). Dùng trình duyệt/profile riêng cho mỗi vai trò. |

---

## 10. Bảo mật khi đưa lên GitHub

- **Không commit** `backend/.env`, `frontend/.env.local` (đã nằm trong `.gitignore`). Kiểm tra bằng `git status` trước khi push.
- README này có mật khẩu tài khoản test ở mục 6.1: chỉ chấp nhận được vì DB là riêng tư. Nếu lỡ lộ `DATABASE_URL`, hãy **đổi mật khẩu DB** trên Neon ngay.
- Thư mục `frontend_vite_backup/` (≈ 265 MB) đã bị loại khỏi git.

---

## 11. Giới hạn đã biết

- **AI service chưa xác thực**: ai biết `session_id` đều vào được phòng AI (nghe phụ đề, tải slide). Hướng xử lý: FastAPI xác nhận token với Flask.
- Dữ liệu của AI service (câu hỏi, câu trả lời, slide, lịch sử phụ đề) **nằm trong RAM**, mất khi khởi động lại.
- **Chất lượng STT chưa chuẩn** (đặc biệt tiếng Việt và giọng có accent); chưa đo WER bằng dữ liệu lớp học thật. Có thể gắn model đã fine-tune qua `WHISPER_MODEL_PATH`.
- Trạng thái phiên học (LIVE/ENDED) do giảng viên bấm, không tự đổi theo giờ.
- Chưa có: tham gia bằng QR, giảng viên duyệt sinh viên, chia sẻ màn hình.
