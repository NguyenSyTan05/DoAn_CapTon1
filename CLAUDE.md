# ClassBridge — hướng dẫn cho Claude / agent

Hệ thống lớp học song ngữ Anh–Việt: giảng viên nói → STT → dịch → phụ đề trực tiếp; kèm chia sẻ slide và hỏi đáp ẩn danh. Chi tiết cài đặt: `README.md`. Luồng sự kiện: `docs/LuongSuKien_ClassBridge.docx`.

## Kiến trúc (3 dịch vụ)

| Khối | Thư mục | Công nghệ | Cổng |
|---|---|---|---|
| Frontend | `frontend/` | Next.js 16, React 19, TypeScript | 4000 |
| Backend tài khoản/lớp | `backend/` | Flask, JWT, SQLAlchemy, PostgreSQL (Neon) | 5000 |
| Backend AI realtime | `ai-service/` | FastAPI, faster-whisper, NLLB-200, MiniLM | 8000 |

- `session_id` (UUID bảng `sessions` ở Flask) nối hai backend. Flask biết ai thuộc lớp nào; FastAPI dùng nó để tách dữ liệu từng phòng (lưu trong RAM, mất khi restart).
- Frontend gọi Flask bằng REST + JWT, gọi FastAPI bằng REST + WebSocket (`?session=<session_id>`).
- Schema DB: `db.sql` + `backend/migrations/001…004`. Thay đổi schema = thêm migration mới, đồng thời cập nhật `db.sql`.

## Lệnh thường dùng

Windows/PowerShell, kích hoạt `.venv` trong `backend/` và `ai-service/` trước (Python **3.11**, không dùng 3.13+).

```powershell
# Flask
cd backend; python app.py
# AI
cd ai-service; python -m uvicorn main:app --host 0.0.0.0 --port 8000
cd ai-service; pytest          # test nằm trong modules/*/test_*.py
# Frontend
cd frontend; npm run dev       # :4000
cd frontend; npm run lint
cd frontend; npm run build     # dùng để kiểm tra lỗi type
```

- `backend/` có test nền trong `backend/tests/` (cài `pip install -r requirements-dev.txt`, chạy `cd backend; python -m pytest tests`; dùng SQLite, không chạm DB Neon).
- Mở giao diện bằng `http://localhost:4000`, không dùng `127.0.0.1`.
- `FRONTEND_ORIGIN` trong `backend/.env` phải là `http://localhost:4000`.

## Cấu trúc code cần biết

**frontend/src**
- `app/`: chỉ là route (App Router), nên giữ mỏng.
- `page/`: component giao diện thật của từng trang (admin, auth, giangvien, sinhvien, landing).
- `components/`: `layout/`, `room/` (Transcript, SlideViewer, QAToast…), `shell/`.
- `services/`: gọi API (`api.js`, `auth.service.js`, `student.service.js`); `lib/`: guard theo vai trò, helper AI.
- Một số file còn là `.js`/`.jsx` (`services/*`, `shell/*`, `sidebar.jsx`). Khi viết mới ưu tiên TypeScript.
- **Next.js 16 có thay đổi lớn so với kiến thức cũ.** Đọc `frontend/AGENTS.md` và `frontend/node_modules/next/dist/docs/` trước khi viết code Next.js.

**backend/routes**: chia theo vai trò: `admin/`, `giangvien/` (`classes/`, `classroom/`, `dashboard.py`), cùng các file cho sinh viên và đăng ký (`student_classes.py`, `register_account_student.py`, `login.py`, `chat.py`…). Dịch vụ dùng chung: `account_service.py`, `audit_service.py`, `verification_service.py`, `email_utils.py`.

**ai-service/modules**: `live_translate/` (STT + dịch + WebSocket), `translate/`, `qa/`, `question_clustering/`, `slides/`. Mỗi module có `router.py`, `schema.py` và test cạnh code.

## Quy ước

- Tên tiếng Việt không dấu xuất hiện nhiều trong route và file: `giangvien` = giảng viên, `sinhvien` = sinh viên, `cauhoi` = câu hỏi, `chitiet` = chi tiết, `lop` = lớp, `tuongtac` = tương tác, `ghilog` = nhật ký. Giữ nguyên tên hiện có, không tự đổi tên.
- Giao diện và thông báo cho người dùng viết bằng tiếng Việt.
- Ba vai trò: sinh viên, giảng viên, quản trị. Mọi endpoint mới phải kiểm tra JWT và vai trò. Đừng chỉ ẩn ở frontend.
- Thay đổi API: sửa backend, rồi `services/` ở frontend, rồi trang dùng nó. Không đổi hợp đồng API một phía.

## Không được làm

- Không commit hoặc in ra `.env`, `DATABASE_URL`, mật khẩu SMTP, API key. Chỉ sửa `.env.example`.
- Không đụng `frontend_vite_backup/`, `frontend/.next/`, `node_modules/` (đã trong `.gitignore`).
- Không dùng driver `postgresql+asyncpg://` cho Flask (phải là `postgresql://` hoặc `postgresql+psycopg2://`).
- Không chạy lệnh ghi vào DB dùng chung của nhóm (Neon) khi chưa hỏi người dùng.
- Không `git push --force`, không push khi chưa được yêu cầu. Nhánh mặc định là `master`.

## Việc tồn đọng đã biết

- README công khai chứa mật khẩu tài khoản test và email thành viên. Cần giữ repo private.
- Test backend mới chỉ phủ đăng nhập, phân quyền (đường bị từ chối) và cấu hình; chưa có test cho frontend.
