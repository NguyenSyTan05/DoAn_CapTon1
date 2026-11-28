import io
import mimetypes
import secrets
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from uuid import UUID, uuid4

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from auth_utils import LECTURER_REQUIRED_MESSAGE, LECTURER_ROLE, role_denied, role_required
from extensions import db
from routes.giangvien.classroom.classroom import (
    _materialize_existing_recurring_sessions,
)


lecturer_classes_bp = Blueprint(
    "lecturer_classes", __name__, url_prefix="/auth/lecturer/classes"
)

VIETNAM_TZ = timezone(timedelta(hours=7))
WEEKDAYS = {
    "MO": (0, "Thứ 2"),
    "TU": (1, "Thứ 3"),
    "WE": (2, "Thứ 4"),
    "TH": (3, "Thứ 5"),
    "FR": (4, "Thứ 6"),
    "SA": (5, "Thứ 7"),
    "SU": (6, "Chủ nhật"),
}
ALLOWED_LECTURE_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".doc",
    ".docx",
    ".odt",
    ".odp",
}
MAX_LECTURE_FILE_SIZE = 20 * 1024 * 1024


def _lecturer_id():
    email = get_jwt_identity()
    if not isinstance(email, str):
        return None
    return db.session.execute(
        text(
            """
            SELECT lecturer_id::text
            FROM lecturers
            WHERE lower(email) = lower(:email) AND is_active = TRUE
            """
        ),
        {"email": email},
    ).scalar_one_or_none()


def _class_or_404(class_id, lecturer_id):
    try:
        normalized_id = str(UUID(class_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return db.session.execute(
        text(
            """
            SELECT class_id::text, class_code
            FROM classes
            WHERE class_id = CAST(:class_id AS uuid)
              AND lecturer_id = CAST(:lecturer_id AS uuid)
              AND status = 'ACTIVE'
            """
        ),
        {"class_id": normalized_id, "lecturer_id": lecturer_id},
    ).mappings().first()


@lecturer_classes_bp.route("", methods=["GET"])
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def list_lecturer_classes():
    try:
        lecturer_id = _lecturer_id()
        if not lecturer_id:
            return jsonify({"message": "Không tìm thấy tài khoản giảng viên."}), 403

        rows = db.session.execute(
            text(
                """
                SELECT
                    c.class_id::text AS id,
                    c.class_name AS name,
                    COALESCE(course.course_code, '') AS "courseCode",
                    c.class_code AS "classCode",
                    c.description,
                    COALESCE(member_counts.student_count, 0) AS "studentCount",
                    COALESCE(schedule_info.total_hours, 0) AS hours,
                    0 AS "hoursLearned",
                    schedule_info.class_time AS "classTime",
                    schedule_info.start_time AS "startTime",
                    schedule_info.end_time AS "endTime",
                    schedule_info.weekday
                FROM classes c
                LEFT JOIN courses course ON course.course_id = c.course_id
                LEFT JOIN (
                    SELECT class_id, COUNT(*) AS student_count
                    FROM class_members
                    WHERE status IS NULL
                       OR lower(status) NOT IN (
                            'inactive', 'removed', 'dropped', 'cancelled', 'canceled'
                       )
                    GROUP BY class_id
                ) member_counts ON member_counts.class_id = c.class_id
                LEFT JOIN LATERAL (
                    SELECT
                        ROUND(
                            COALESCE(SUM(patterns.duration_hours), 0)::numeric,
                            1
                        ) AS total_hours,
                        MIN(patterns.start_label) AS start_time,
                        MIN(patterns.end_label) AS end_time,
                        STRING_AGG(
                            DISTINCT CASE patterns.weekday
                                WHEN 1 THEN 'Thứ 2'
                                WHEN 2 THEN 'Thứ 3'
                                WHEN 3 THEN 'Thứ 4'
                                WHEN 4 THEN 'Thứ 5'
                                WHEN 5 THEN 'Thứ 6'
                                WHEN 6 THEN 'Thứ 7'
                                WHEN 7 THEN 'Chủ nhật'
                                ELSE NULL
                            END,
                            ', '
                        ) AS weekday,
                        STRING_AGG(
                            DISTINCT CONCAT(
                                CASE patterns.weekday
                                    WHEN 1 THEN 'Thứ 2'
                                    WHEN 2 THEN 'Thứ 3'
                                    WHEN 3 THEN 'Thứ 4'
                                    WHEN 4 THEN 'Thứ 5'
                                    WHEN 5 THEN 'Thứ 6'
                                    WHEN 6 THEN 'Thứ 7'
                                    WHEN 7 THEN 'Chủ nhật'
                                    ELSE ''
                                END,
                                ' ',
                                patterns.start_label,
                                ' - ',
                                patterns.end_label
                            ),
                            ' | '
                        ) AS class_time
                    FROM (
                        SELECT
                            EXTRACT(
                                ISODOW FROM cs.start_time AT TIME ZONE 'Asia/Ho_Chi_Minh'
                            )::int AS weekday,
                            TO_CHAR(
                                cs.start_time AT TIME ZONE 'Asia/Ho_Chi_Minh',
                                'HH24:MI'
                            ) AS start_label,
                            TO_CHAR(
                                cs.end_time AT TIME ZONE 'Asia/Ho_Chi_Minh',
                                'HH24:MI'
                            ) AS end_label,
                            EXTRACT(
                                EPOCH FROM (cs.end_time - cs.start_time)
                            ) / 3600.0 AS duration_hours
                        FROM class_schedules cs
                        WHERE cs.class_id = c.class_id
                          AND cs.schedule_type = 'CLASS'
                          AND cs.status <> 'CANCELLED'
                    ) patterns
                ) schedule_info ON TRUE
                WHERE c.lecturer_id = CAST(:lecturer_id AS uuid)
                  AND c.status = 'ACTIVE'
                ORDER BY c.created_at DESC
                """
            ),
            {"lecturer_id": lecturer_id},
        ).mappings().all()
        return jsonify({"classes": [dict(row) for row in rows]})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to load lecturer classes")
        return jsonify({"message": "Không thể tải danh sách lớp học."}), 500


@lecturer_classes_bp.route("", methods=["POST"])
@jwt_required()
def create_lecturer_class():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"message": "Dữ liệu lớp học không hợp lệ."}), 400

    name = body.get("name")
    course_code = body.get("courseCode")
    description = body.get("description", "")
    raw_hours = body.get("hours")
    start_date_value = body.get("startDate")
    end_date_value = body.get("endDate")
    schedules = body.get("weeklySchedules")

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        return jsonify({"message": "Tên môn học là bắt buộc và tối đa 150 ký tự."}), 400
    if (
        not isinstance(course_code, str)
        or not course_code.strip()
        or len(course_code.strip()) > 30
    ):
        return jsonify({"message": "Mã môn học là bắt buộc và tối đa 30 ký tự."}), 400
    if not isinstance(description, str):
        return jsonify({"message": "Mô tả lớp học không hợp lệ."}), 400
    if not isinstance(schedules, list) or not 1 <= len(schedules) <= 21:
        return jsonify({"message": "Vui lòng thêm từ 1 đến 21 buổi học mỗi tuần."}), 400

    try:
        duration_hours = Decimal(str(raw_hours))
        if not duration_hours.is_finite() or duration_hours <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return jsonify({"message": "Số giờ học phải lớn hơn 0."}), 400

    try:
        start_date = date.fromisoformat(start_date_value)
        end_date = date.fromisoformat(end_date_value)
        if end_date < start_date:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"message": "Khoảng ngày học không hợp lệ."}), 400

    schedule_defs = []
    for schedule in schedules:
        if not isinstance(schedule, dict):
            return jsonify({"message": "Thông tin buổi học không hợp lệ."}), 400
        weekday = str(schedule.get("weekday", "")).upper()
        raw_start = str(schedule.get("startTime", schedule.get("time", "")))
        raw_end = str(schedule.get("endTime", ""))
        try:
            start_time = time.fromisoformat(raw_start)
            end_time = time.fromisoformat(raw_end)
        except ValueError:
            return jsonify({"message": "Giờ học không hợp lệ."}), 400
        if weekday not in WEEKDAYS or end_time <= start_time:
            return jsonify({
                "message": "Mỗi buổi học cần có thứ và giờ kết thúc sau giờ bắt đầu."
            }), 400
        schedule_defs.append((weekday, start_time, end_time))

    if len({(weekday, start_time) for weekday, start_time, _ in schedule_defs}) != len(schedule_defs):
        return jsonify({
            "message": "Không thể tạo nhiều buổi trùng thứ và giờ bắt đầu."
        }), 400
    for weekday, _, _ in schedule_defs:
        first_class_day = start_date + timedelta(
            days=(WEEKDAYS[weekday][0] - start_date.weekday()) % 7
        )
        if first_class_day > end_date:
            return jsonify({
                "message": "Khoảng ngày đã chọn không có ngày học tương ứng với lịch trong tuần."
            }), 400

    # Giữ thứ tự cũ: kiểm tra dữ liệu gửi lên trước, rồi mới kiểm tra vai trò.
    denied = role_denied(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
    if denied:
        return denied

    try:
        lecturer_id = _lecturer_id()
        if not lecturer_id:
            return jsonify({"message": "Không tìm thấy tài khoản giảng viên."}), 403

        course_id = db.session.execute(
            text(
                """
                INSERT INTO courses (course_code, course_name, description)
                VALUES (:course_code, :course_name, NULLIF(:description, ''))
                ON CONFLICT (course_code)
                DO UPDATE SET course_code = EXCLUDED.course_code
                RETURNING course_id::text
                """
            ),
            {
                "course_code": course_code.strip(),
                "course_name": name.strip(),
                "description": description.strip(),
            },
        ).scalar_one()

        class_code = f"{course_code.strip()}-{uuid4().hex[:8].upper()}"
        class_id = db.session.execute(
            text(
                """
                INSERT INTO classes (
                    course_id, lecturer_id, class_code, class_name, description,
                    semester, academic_year, status
                )
                VALUES (
                    CAST(:course_id AS uuid), CAST(:lecturer_id AS uuid),
                    :class_code, :class_name, NULLIF(:description, ''),
                    :semester, :academic_year, 'ACTIVE'
                )
                RETURNING class_id::text
                """
            ),
            {
                "course_id": course_id,
                "lecturer_id": lecturer_id,
                "class_code": class_code,
                "class_name": name.strip(),
                "description": description.strip(),
                "semester": f"{start_date.isoformat()} - {end_date.isoformat()}",
                "academic_year": str(start_date.year)
                if start_date.year == end_date.year
                else f"{start_date.year}-{end_date.year}",
            },
        ).scalar_one()

        weekday_offsets = {
            code: day_offset for code, (day_offset, _) in WEEKDAYS.items()
        }
        schedule_ids = []
        for weekday, start_time, end_time in schedule_defs:
            class_day = start_date + timedelta(
                days=(weekday_offsets[weekday] - start_date.weekday()) % 7
            )
            while class_day <= end_date:
                start_at = datetime.combine(
                    class_day, start_time, tzinfo=VIETNAM_TZ
                )
                end_at = datetime.combine(class_day, end_time, tzinfo=VIETNAM_TZ)
                schedule_id = db.session.execute(
                    text(
                        """
                        INSERT INTO class_schedules (
                            class_id, schedule_type, title, description,
                            start_time, end_time, status, created_by_lecturer_id
                        )
                        VALUES (
                            CAST(:class_id AS uuid), 'CLASS', :title,
                            NULLIF(:description, ''), :start_time, :end_time,
                            'SCHEDULED', CAST(:lecturer_id AS uuid)
                        )
                        RETURNING schedule_id::text
                        """
                    ),
                    {
                        "class_id": class_id,
                        "title": name.strip(),
                        "description": description.strip(),
                        "start_time": start_at,
                        "end_time": end_at,
                        "lecturer_id": lecturer_id,
                    },
                ).scalar_one()
                session_id = db.session.execute(
                    text(
                        """
                        INSERT INTO sessions (
                            class_id, schedule_id, session_title, status, join_code
                        )
                        VALUES (
                            CAST(:class_id AS uuid), CAST(:schedule_id AS uuid),
                            :title, 'SCHEDULED', :join_code
                        )
                        RETURNING session_id::text
                        """
                    ),
                    {
                        "class_id": class_id,
                        "schedule_id": schedule_id,
                        "title": name.strip(),
                        "join_code": secrets.token_urlsafe(9),
                    },
                ).scalar_one()
                schedule_ids.append(
                    {
                        "weekday": weekday,
                        "date": class_day.isoformat(),
                        "scheduleId": schedule_id,
                        "sessionId": session_id,
                    }
                )
                class_day += timedelta(days=7)

        db.session.commit()
        return jsonify(
            {
                "id": class_id,
                "classCode": class_code,
                "scheduleIds": schedule_ids,
                "message": "Đã tạo lớp học.",
            }
        ), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.exception("Lecturer class creation constraint failed")
        return jsonify({"message": "Mã môn học hoặc lớp học đã tồn tại."}), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create lecturer class")
        return jsonify({"message": "Không thể lưu lớp học. Vui lòng thử lại."}), 500


@lecturer_classes_bp.route("/<class_id>", methods=["PUT"])
@jwt_required()
def update_lecturer_class(class_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"message": "Dữ liệu cập nhật không hợp lệ."}), 400
    name = body.get("name")
    description = body.get("description", "")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        return jsonify({"message": "Tên môn học là bắt buộc và tối đa 150 ký tự."}), 400
    if not isinstance(description, str):
        return jsonify({"message": "Mô tả lớp học không hợp lệ."}), 400
    # Giữ thứ tự cũ: kiểm tra dữ liệu gửi lên trước, rồi mới kiểm tra vai trò.
    denied = role_denied(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
    if denied:
        return denied

    try:
        lecturer_id = _lecturer_id()
        if not lecturer_id:
            return jsonify({"message": "Không tìm thấy tài khoản giảng viên."}), 403
        owned_class = _class_or_404(class_id, lecturer_id)
        if not owned_class:
            return jsonify({"message": "Không tìm thấy lớp học."}), 404
        db.session.execute(
            text(
                """
                UPDATE classes
                SET class_name = :name, description = NULLIF(:description, ''),
                    updated_at = NOW()
                WHERE class_id = CAST(:class_id AS uuid)
                  AND lecturer_id = CAST(:lecturer_id AS uuid)
                """
            ),
            {
                "name": name.strip(),
                "description": description.strip(),
                "class_id": owned_class["class_id"],
                "lecturer_id": lecturer_id,
            },
        )
        db.session.execute(
            text(
                """
                UPDATE class_schedules
                SET title = :name, description = NULLIF(:description, ''),
                    updated_at = NOW()
                WHERE class_id = CAST(:class_id AS uuid)
                """
            ),
            {
                "name": name.strip(),
                "description": description.strip(),
                "class_id": owned_class["class_id"],
            },
        )
        db.session.commit()
        return jsonify({"message": "Đã cập nhật lớp học."})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update lecturer class")
        return jsonify({"message": "Không thể cập nhật lớp học."}), 500


@lecturer_classes_bp.route("/<class_id>", methods=["DELETE"])
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def delete_lecturer_class(class_id):
    try:
        lecturer_id = _lecturer_id()
        if not lecturer_id:
            return jsonify({"message": "Không tìm thấy tài khoản giảng viên."}), 403
        owned_class = _class_or_404(class_id, lecturer_id)
        if not owned_class:
            return jsonify({"message": "Không tìm thấy lớp học."}), 404
        db.session.execute(
            text(
                """
                UPDATE classes
                SET status = 'INACTIVE', updated_at = NOW()
                WHERE class_id = CAST(:class_id AS uuid)
                  AND lecturer_id = CAST(:lecturer_id AS uuid)
                """
            ),
            {
                "class_id": owned_class["class_id"],
                "lecturer_id": lecturer_id,
            },
        )
        db.session.commit()
        return jsonify({"message": "Đã xóa lớp học."})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete lecturer class")
        return jsonify({"message": "Không thể xóa lớp học."}), 500


@lecturer_classes_bp.route("/<class_id>/sessions", methods=["GET"])
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def list_lecturer_class_sessions(class_id):
    try:
        lecturer_id = _lecturer_id()
        if not lecturer_id:
            return jsonify({"message": "Không tìm thấy tài khoản giảng viên."}), 403
        _materialize_existing_recurring_sessions(lecturer_id)
        db.session.commit()
        owned_class = _class_or_404(class_id, lecturer_id)
        if not owned_class:
            return jsonify({"message": "Không tìm thấy lớp học."}), 404
        rows = db.session.execute(
            text(
                """
                SELECT
                    cs.schedule_id::text AS id,
                    cs.title,
                    COALESCE(cs.room_name, '') AS room,
                    TO_CHAR(
                        cs.start_time AT TIME ZONE 'Asia/Ho_Chi_Minh',
                        'DD/MM/YYYY'
                    ) AS "dateLabel",
                    CASE EXTRACT(
                        ISODOW FROM cs.start_time AT TIME ZONE 'Asia/Ho_Chi_Minh'
                    )::int
                        WHEN 1 THEN 'Thứ 2'
                        WHEN 2 THEN 'Thứ 3'
                        WHEN 3 THEN 'Thứ 4'
                        WHEN 4 THEN 'Thứ 5'
                        WHEN 5 THEN 'Thứ 6'
                        WHEN 6 THEN 'Thứ 7'
                        WHEN 7 THEN 'Chủ nhật'
                        ELSE ''
                    END AS weekday,
                    CASE EXTRACT(
                        ISODOW FROM cs.start_time AT TIME ZONE 'Asia/Ho_Chi_Minh'
                    )::int
                        WHEN 1 THEN 'MO'
                        WHEN 2 THEN 'TU'
                        WHEN 3 THEN 'WE'
                        WHEN 4 THEN 'TH'
                        WHEN 5 THEN 'FR'
                        WHEN 6 THEN 'SA'
                        WHEN 7 THEN 'SU'
                        ELSE ''
                    END AS "weekdayCode",
                    FALSE AS recurring,
                    TO_CHAR(
                        cs.start_time AT TIME ZONE 'Asia/Ho_Chi_Minh', 'HH24:MI'
                    ) AS "startTimeLabel",
                    TO_CHAR(
                        cs.end_time AT TIME ZONE 'Asia/Ho_Chi_Minh', 'HH24:MI'
                    ) AS "endTimeLabel",
                    EXISTS (
                        SELECT 1
                        FROM lecture_files lf
                        JOIN sessions s ON s.session_id = lf.session_id
                        WHERE s.schedule_id = cs.schedule_id
                          AND lf.file_category IN ('LECTURE', 'SLIDE')
                    ) AS "hasSlides"
                FROM class_schedules cs
                WHERE cs.class_id = CAST(:class_id AS uuid)
                  AND cs.schedule_type = 'CLASS'
                  AND cs.status <> 'CANCELLED'
                ORDER BY cs.start_time
                """
            ),
            {"class_id": owned_class["class_id"]},
        ).mappings().all()
        return jsonify({"sessions": [dict(row) for row in rows]})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to load class schedules")
        return jsonify({"message": "Không thể tải danh sách buổi học."}), 500


@lecturer_classes_bp.route(
    "/<class_id>/sessions/<schedule_id>/upload-slides", methods=["POST"]
)
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def upload_lecture_file(class_id, schedule_id):
    try:
        lecturer_id = _lecturer_id()
        if not lecturer_id:
            return jsonify({"message": "Không tìm thấy tài khoản giảng viên."}), 403
        owned_class = _class_or_404(class_id, lecturer_id)
        if not owned_class:
            return jsonify({"message": "Không tìm thấy lớp học."}), 404
        try:
            normalized_schedule_id = str(UUID(schedule_id))
        except (ValueError, TypeError, AttributeError):
            return jsonify({"message": "Buổi học không hợp lệ."}), 400

        schedule = db.session.execute(
            text(
                """
                SELECT cs.schedule_id::text, s.session_id::text
                FROM class_schedules cs
                LEFT JOIN sessions s ON s.schedule_id = cs.schedule_id
                WHERE cs.schedule_id = CAST(:schedule_id AS uuid)
                  AND cs.class_id = CAST(:class_id AS uuid)
                  AND cs.schedule_type = 'CLASS'
                  AND cs.status <> 'CANCELLED'
                """
            ),
            {
                "schedule_id": normalized_schedule_id,
                "class_id": owned_class["class_id"],
            },
        ).mappings().first()
        if not schedule or not schedule["session_id"]:
            return jsonify({"message": "Không tìm thấy buổi học."}), 404

        uploaded_file = request.files.get("file")
        if not uploaded_file or not uploaded_file.filename:
            return jsonify({"message": "Vui lòng chọn file bài giảng."}), 400
        original_filename = PurePath(uploaded_file.filename).name
        extension = PurePath(original_filename).suffix.lower()
        if extension not in ALLOWED_LECTURE_EXTENSIONS:
            return jsonify({
                "message": "Chỉ hỗ trợ file PDF, PowerPoint, Word, ODT hoặc ODP."
            }), 400
        file_data = uploaded_file.stream.read(MAX_LECTURE_FILE_SIZE + 1)
        if not file_data:
            return jsonify({"message": "File tải lên đang trống."}), 400
        if len(file_data) > MAX_LECTURE_FILE_SIZE:
            return jsonify({"message": "Dung lượng file tối đa là 20 MB."}), 413

        db.session.execute(
            text(
                """
                INSERT INTO lecture_files (
                    class_id, session_id, uploaded_by_lecturer_id,
                    file_name, original_file_name, mime_type, file_extension,
                    file_size_bytes, storage_type, file_data, file_category,
                    visibility
                )
                VALUES (
                    CAST(:class_id AS uuid), CAST(:session_id AS uuid),
                    CAST(:lecturer_id AS uuid), :file_name, :original_file_name,
                    :mime_type, :file_extension, :file_size, 'BYTEA', :file_data,
                    'LECTURE', 'CLASS'
                )
                """
            ),
            {
                "class_id": owned_class["class_id"],
                "session_id": schedule["session_id"],
                "lecturer_id": lecturer_id,
                "file_name": original_filename,
                "original_file_name": original_filename,
                "mime_type": mimetypes.guess_type(original_filename)[0] or "application/octet-stream",
                "file_extension": extension.lstrip("."),
                "file_size": len(file_data),
                "file_data": file_data,
            },
        )
        db.session.commit()
        return jsonify({"message": "Đã tải bài giảng lên.", "slides": 0}), 201
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to upload lecturer lecture file")
        return jsonify({"message": "Không thể tải bài giảng lên."}), 500


# =====================================================================
# Excel Template & Import cho Danh sách lớp học
# =====================================================================
def _norm_header(value) -> str:
    text_val = str(value or "").strip().lower()
    nfd = unicodedata.normalize("NFD", text_val)
    no_accent = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return " ".join(no_accent.replace("đ", "d").replace("_", " ").split())


def _parse_weekday_cell(raw) -> str | None:
    norm = _norm_header(raw)
    if not norm:
        return None
    mapping = {
        "mo": "MO", "mon": "MO", "monday": "MO", "thu 2": "MO", "t2": "MO", "2": "MO",
        "tu": "TU", "tue": "TU", "tuesday": "TU", "thu 3": "TU", "t3": "TU", "3": "TU",
        "we": "WE", "wed": "WE", "wednesday": "WE", "thu 4": "WE", "t4": "WE", "4": "WE",
        "th": "TH", "thu": "TH", "thursday": "TH", "thu 5": "TH", "t5": "TH", "5": "TH",
        "fr": "FR", "fri": "FR", "friday": "FR", "thu 6": "FR", "t6": "FR", "6": "FR",
        "sa": "SA", "sat": "SA", "saturday": "SA", "thu 7": "SA", "t7": "SA", "7": "SA",
        "su": "SU", "sun": "SU", "sunday": "SU", "chu nhat": "SU", "cn": "SU", "8": "SU",
    }
    return mapping.get(norm)


def _parse_date_cell(raw) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time_cell(raw) -> time | None:
    if isinstance(raw, datetime):
        return raw.time().replace(second=0, microsecond=0)
    if isinstance(raw, time):
        return raw.replace(second=0, microsecond=0)
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).time().replace(second=0, microsecond=0)
        except ValueError:
            continue
    return None


@lecturer_classes_bp.route("/template", methods=["GET"])
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def download_classes_excel_template():
    try:
        from openpyxl import Workbook
    except ImportError:
        return jsonify({"message": "Máy chủ chưa cài openpyxl để tạo file mẫu."}), 503

    wb = Workbook()
    ws = wb.active
    ws.title = "Danh sach lop"
    ws.append([
        "Ma mon hoc",
        "Ten mon hoc",
        "Tong so gio",
        "Ngay bat dau",
        "Ngay ket thuc",
        "Thu trong tuan",
        "Thoi gian bat dau",
        "Thoi gian ket thuc",
        "Mo ta",
    ])
    today = date.today()
    ws.append([
        "CS101",
        "Nhap mon Khoa hoc May tinh",
        30,
        today.isoformat(),
        (today + timedelta(days=60)).isoformat(),
        "Thu 3",
        "08:00",
        "10:00",
        "Lop mau EMI",
    ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="mau_import_lop.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@lecturer_classes_bp.route("/import-excel", methods=["POST"])
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def import_classes_from_excel():
    try:
        from openpyxl import load_workbook
    except ImportError:
        return jsonify({"message": "Máy chủ chưa cài openpyxl để đọc file Excel."}), 503

    lecturer_id = _lecturer_id()
    if not lecturer_id:
        return jsonify({"message": "Không tìm thấy tài khoản giảng viên."}), 403

    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"message": "Vui lòng chọn file Excel (.xlsx)."}), 400
    ext = PurePath(uploaded.filename).suffix.lower()
    if ext not in (".xlsx", ".xlsm"):
        return jsonify({"message": "Chỉ hỗ trợ file Excel định dạng .xlsx."}), 400

    try:
        wb = load_workbook(io.BytesIO(uploaded.read()), data_only=True)
    except Exception:
        return jsonify({"message": "Không thể đọc file Excel. Hãy kiểm tra lại định dạng file."}), 400

    ws = wb.active
    rows_iter = list(ws.iter_rows(values_only=True))
    if len(rows_iter) < 2:
        return jsonify({"message": "File Excel chưa có dữ liệu lớp học."}), 400

    header_map: dict[str, int] = {}
    aliases = {
        "course_code": {"ma mon hoc", "coursecode", "course code", "ma mon"},
        "name": {"ten mon hoc", "ten lop", "name", "class name", "course name"},
        "hours": {"tong so gio", "so gio", "so gio hoc", "hours"},
        "start_date": {"ngay bat dau", "start date", "startdate"},
        "end_date": {"ngay ket thuc", "end date", "enddate"},
        "weekday": {"thu trong tuan", "thu", "weekday"},
        "start_time": {"thoi gian bat dau", "gio bat dau", "start time", "starttime"},
        "end_time": {"thoi gian ket thuc", "gio ket thuc", "end time", "endtime"},
        "description": {"mo ta", "description", "ghi chu"},
    }
    for col_idx, raw_hdr in enumerate(rows_iter[0]):
        norm = _norm_header(raw_hdr)
        for key, candidates in aliases.items():
            if norm in candidates and key not in header_map:
                header_map[key] = col_idx

    if "course_code" not in header_map or "name" not in header_map:
        return jsonify({
            "message": "Thiếu cột bắt buộc 'Ma mon hoc' hoặc 'Ten mon hoc'. Hãy tải file mẫu của hệ thống."
        }), 400

    weekday_offsets = {code: day_offset for code, (day_offset, _) in WEEKDAYS.items()}
    created = 0
    row_errors = []

    def _cell(row_vals, key):
        idx = header_map.get(key)
        if idx is None or idx >= len(row_vals):
            return None
        return row_vals[idx]

    for row_num, row_vals in enumerate(rows_iter[1:], start=2):
        if not any(v is not None and str(v).strip() != "" for v in row_vals):
            continue
        errs = []
        course_code = str(_cell(row_vals, "course_code") or "").strip()
        name = str(_cell(row_vals, "name") or "").strip()
        description = str(_cell(row_vals, "description") or "").strip()
        if not course_code or len(course_code) > 30:
            errs.append("Mã môn học không hợp lệ")
        if not name or len(name) > 150:
            errs.append("Tên môn học không hợp lệ")

        raw_hours = _cell(row_vals, "hours")
        try:
            hours_val = Decimal(str(raw_hours if raw_hours not in (None, "") else "30"))
            if not hours_val.is_finite() or hours_val <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            errs.append("Số giờ học phải > 0")

        today = date.today()
        start_d = _parse_date_cell(_cell(row_vals, "start_date")) or today
        end_d = _parse_date_cell(_cell(row_vals, "end_date")) or (start_d + timedelta(days=56))
        if end_d < start_d:
            errs.append("Ngày kết thúc phải sau ngày bắt đầu")

        weekday = _parse_weekday_cell(_cell(row_vals, "weekday")) or "MO"
        start_t = _parse_time_cell(_cell(row_vals, "start_time")) or time(8, 0)
        end_t = _parse_time_cell(_cell(row_vals, "end_time")) or time(10, 0)
        if end_t <= start_t:
            errs.append("Giờ kết thúc phải sau giờ bắt đầu")

        if errs:
            row_errors.append({"row": row_num, "errors": errs})
            continue

        try:
            course_id = db.session.execute(
                text(
                    """
                    INSERT INTO courses (course_code, course_name, description)
                    VALUES (:course_code, :course_name, NULLIF(:description, ''))
                    ON CONFLICT (course_code)
                    DO UPDATE SET course_code = EXCLUDED.course_code
                    RETURNING course_id::text
                    """
                ),
                {
                    "course_code": course_code,
                    "course_name": name,
                    "description": description,
                },
            ).scalar_one()

            class_code = f"{course_code}-{uuid4().hex[:8].upper()}"
            class_id = db.session.execute(
                text(
                    """
                    INSERT INTO classes (
                        course_id, lecturer_id, class_code, class_name, description,
                        semester, academic_year, status
                    )
                    VALUES (
                        CAST(:course_id AS uuid), CAST(:lecturer_id AS uuid),
                        :class_code, :class_name, NULLIF(:description, ''),
                        :semester, :academic_year, 'ACTIVE'
                    )
                    RETURNING class_id::text
                    """
                ),
                {
                    "course_id": course_id,
                    "lecturer_id": lecturer_id,
                    "class_code": class_code,
                    "class_name": name,
                    "description": description,
                    "semester": f"{start_d.isoformat()} - {end_d.isoformat()}",
                    "academic_year": str(start_d.year) if start_d.year == end_d.year else f"{start_d.year}-{end_d.year}",
                },
            ).scalar_one()

            class_day = start_d + timedelta(days=(weekday_offsets[weekday] - start_d.weekday()) % 7)
            if class_day > end_d:
                class_day = start_d
            while class_day <= end_d:
                start_at = datetime.combine(class_day, start_t, tzinfo=VIETNAM_TZ)
                end_at = datetime.combine(class_day, end_t, tzinfo=VIETNAM_TZ)
                schedule_id = db.session.execute(
                    text(
                        """
                        INSERT INTO class_schedules (
                            class_id, schedule_type, title, description,
                            start_time, end_time, status, created_by_lecturer_id
                        )
                        VALUES (
                            CAST(:class_id AS uuid), 'CLASS', :title,
                            NULLIF(:description, ''), :start_time, :end_time,
                            'SCHEDULED', CAST(:lecturer_id AS uuid)
                        )
                        RETURNING schedule_id::text
                        """
                    ),
                    {
                        "class_id": class_id,
                        "title": name,
                        "description": description,
                        "start_time": start_at,
                        "end_time": end_at,
                        "lecturer_id": lecturer_id,
                    },
                ).scalar_one()
                db.session.execute(
                    text(
                        """
                        INSERT INTO sessions (
                            class_id, schedule_id, session_title, status, join_code
                        )
                        VALUES (
                            CAST(:class_id AS uuid), CAST(:schedule_id AS uuid),
                            :title, 'SCHEDULED', :join_code
                        )
                        """
                    ),
                    {
                        "class_id": class_id,
                        "schedule_id": schedule_id,
                        "title": name,
                        "join_code": secrets.token_urlsafe(9),
                    },
                )
                class_day += timedelta(days=7)

            db.session.commit()
            created += 1
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed importing Excel row %s", row_num)
            row_errors.append({"row": row_num, "errors": ["Không thể lưu lớp học vào cơ sở dữ liệu"]})

    return jsonify({
        "message": f"Đã nhập thành công {created} lớp học." if created else "Không có lớp học nào được nhập.",
        "created": created,
        "errors": row_errors,
    }), 201 if created else 400
