"""Sinh viên tham gia lớp bằng MÃ LỚP và xem các lớp của mình.

POST /auth/student/classes/join   {code}  -> thêm vào class_members (vào lớp ngay)
GET  /auth/student/classes                -> danh sách lớp đã tham gia + phiên đang diễn ra

TODO (sau này): chế độ "chờ giảng viên duyệt" và tham gia bằng QR.
"""

from uuid import UUID

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from auth_utils import STUDENT_ROLES, role_denied, role_required
from extensions import db
from request_limits import request_limit_exceeded


student_classes_bp = Blueprint(
    "student_classes", __name__, url_prefix="/auth/student/classes"
)

student_sessions_bp = Blueprint(
    "student_sessions", __name__, url_prefix="/auth/student/sessions"
)

MAX_CODE_LENGTH = 30  # classes.class_code là VARCHAR(30)


def _current_student():
    """Trả về sinh viên đang đăng nhập (đang hoạt động) hoặc None."""
    email = get_jwt_identity()
    if not isinstance(email, str):
        return None
    return db.session.execute(
        text(
            """
            SELECT student_id::text AS id, full_name, email
            FROM students
            WHERE lower(email) = lower(:email) AND is_active = TRUE
            """
        ),
        {"email": email},
    ).mappings().first()


def _audit(student, class_row, joined_via="CODE"):
    """Ghi audit log; lỗi ghi log không làm hỏng việc tham gia lớp.

    Columns actor_email / entity_name / status do not exist in audit_logs
    (db.sql). Pack them into the details JSONB field instead.
    """
    import json as _json
    try:
        details = _json.dumps(
            {
                "email": student["email"],
                "class_name": class_row["class_name"],
                "joined_via": joined_via,
            },
            ensure_ascii=False,
        )
        db.session.execute(
            text(
                """
                INSERT INTO audit_logs (
                    action, description, actor_role, student_id,
                    entity_type, entity_id, details, created_at
                ) VALUES (
                    :action, :description, 'STUDENT',
                    CAST(:student_id AS uuid), 'class',
                    CAST(:class_id AS uuid),
                    CAST(:details AS jsonb), NOW()
                )
                """
            ),
            {
                "action": "Tham gia lớp",
                "description": (
                    f"{student['full_name']} tham gia lớp {class_row['class_name']}"
                    f" bằng {joined_via}"
                ),
                "student_id": student["id"],
                "class_id": class_row["class_id"],
                "details": details,
            },
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.warning("Audit log for class join was not recorded")


def _current_session(class_id):
    """Phiên nên đưa sinh viên vào: đang LIVE, nếu không thì buổi SCHEDULED gần nhất chưa kết thúc."""
    row = db.session.execute(
        text(
            """
            SELECT s.session_id::text AS id, s.session_title AS title, s.status,
                   cs.start_time AS "startTime", cs.end_time AS "endTime"
            FROM sessions s
            LEFT JOIN class_schedules cs ON cs.schedule_id = s.schedule_id
            WHERE s.class_id = CAST(:class_id AS uuid)
              AND (
                    s.status = 'LIVE'
                 OR (s.status = 'SCHEDULED' AND (cs.end_time IS NULL OR cs.end_time >= NOW()))
              )
            ORDER BY (s.status = 'LIVE') DESC, cs.start_time NULLS LAST
            LIMIT 1
            """
        ),
        {"class_id": class_id},
    ).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "startTime": row["startTime"].isoformat() if row["startTime"] else None,
        "endTime": row["endTime"].isoformat() if row["endTime"] else None,
    }


@student_classes_bp.route("/join", methods=["POST"])
@jwt_required()
def join_class_by_code():
    if request_limit_exceeded(("join-class", request.remote_addr), 20, 900):
        return jsonify({"message": "Bạn thử quá nhiều lần. Vui lòng thử lại sau."}), 429

    body = request.get_json(silent=True)
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str) or not code.strip():
        return jsonify({"message": "Vui lòng nhập mã lớp."}), 400
    code = code.strip().upper()
    if len(code) > MAX_CODE_LENGTH:
        return jsonify({"message": "Mã lớp không hợp lệ."}), 400

    # Giữ thứ tự cũ: kiểm tra dữ liệu đầu vào trước, rồi mới kiểm tra vai trò.
    denied = role_denied(*STUDENT_ROLES, message="Chỉ sinh viên mới có thể tham gia lớp.")
    if denied:
        return denied
    try:
        student = _current_student()
        if not student:
            return jsonify({"message": "Chỉ sinh viên mới có thể tham gia lớp."}), 403

        class_row = db.session.execute(
            text(
                """
                SELECT c.class_id::text AS class_id, c.class_code, c.class_name,
                       l.full_name AS lecturer_name
                FROM classes c
                JOIN lecturers l ON l.lecturer_id = c.lecturer_id
                WHERE upper(c.class_code) = :code AND c.status = 'ACTIVE'
                """
            ),
            {"code": code},
        ).mappings().first()
        # Cùng một thông báo cho "không tồn tại" và "lớp ngừng hoạt động"
        if not class_row:
            return jsonify({"message": "Mã lớp không hợp lệ hoặc lớp không còn hoạt động."}), 404

        member = db.session.execute(
            text(
                """
                SELECT upper(status) AS status FROM class_members
                WHERE class_id = CAST(:class_id AS uuid)
                  AND student_id = CAST(:student_id AS uuid)
                """
            ),
            {"class_id": class_row["class_id"], "student_id": student["id"]},
        ).mappings().first()

        already_member = False
        if member and member["status"] == "REMOVED":
            return jsonify({"message": "Bạn không thể tham gia lớp này."}), 403
        if member and member["status"] == "ACTIVE":
            already_member = True
        elif member:  # INACTIVE -> kích hoạt lại
            db.session.execute(
                text(
                    """
                    UPDATE class_members
                    SET status = 'ACTIVE', joined_via = 'CODE', joined_at = NOW()
                    WHERE class_id = CAST(:class_id AS uuid)
                      AND student_id = CAST(:student_id AS uuid)
                    """
                ),
                {"class_id": class_row["class_id"], "student_id": student["id"]},
            )
            db.session.commit()
        else:
            db.session.execute(
                text(
                    """
                    INSERT INTO class_members (class_id, student_id, status, joined_via)
                    VALUES (CAST(:class_id AS uuid), CAST(:student_id AS uuid),
                            'ACTIVE', 'CODE')
                    ON CONFLICT (class_id, student_id) DO NOTHING
                    """
                ),
                {"class_id": class_row["class_id"], "student_id": student["id"]},
            )
            db.session.commit()

        if not already_member:
            _audit(student, class_row)

        return jsonify(
            {
                "success": True,
                "alreadyMember": already_member,
                # Để giao diện đưa sinh viên thẳng vào phòng học (hoặc phòng chờ) thay vì quay lại danh sách
                "session": _current_session(class_row["class_id"]),
                "class": {
                    "id": class_row["class_id"],
                    "code": class_row["class_code"],
                    "name": class_row["class_name"],
                    "lecturerName": class_row["lecturer_name"],
                },
            }
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Student class join failed")
        return jsonify({"message": "Không thể tham gia lớp lúc này. Vui lòng thử lại."}), 500


@student_classes_bp.route("", methods=["GET"])
@role_required(*STUDENT_ROLES, message="Chỉ sinh viên mới xem được danh sách này.")
def list_my_classes():
    try:
        student = _current_student()
        if not student:
            return jsonify({"message": "Chỉ sinh viên mới xem được danh sách này."}), 403

        rows = db.session.execute(
            text(
                """
                SELECT
                    c.class_id::text AS id,
                    c.class_code AS code,
                    c.class_name AS name,
                    l.full_name AS "lecturerName",
                    live.session_id::text AS "liveSessionId",
                    live.session_title AS "liveSessionTitle",
                    live.started_at AS "liveStartedAt",
                    nxt.session_id::text AS "nextSessionId",
                    nxt.session_title AS "nextSessionTitle",
                    nxt.start_time AS "nextStartTime",
                    nxt.end_time AS "nextEndTime"
                FROM class_members cm
                JOIN classes c ON c.class_id = cm.class_id
                JOIN lecturers l ON l.lecturer_id = c.lecturer_id
                LEFT JOIN LATERAL (
                    SELECT s.session_id, s.session_title, s.started_at
                    FROM sessions s
                    WHERE s.class_id = c.class_id AND s.status = 'LIVE'
                    ORDER BY s.started_at DESC NULLS LAST
                    LIMIT 1
                ) live ON TRUE
                LEFT JOIN LATERAL (
                    SELECT s.session_id, s.session_title, cs.start_time, cs.end_time
                    FROM sessions s
                    LEFT JOIN class_schedules cs ON cs.schedule_id = s.schedule_id
                    WHERE s.class_id = c.class_id AND s.status = 'SCHEDULED'
                      AND (cs.end_time IS NULL OR cs.end_time >= NOW())
                    ORDER BY cs.start_time NULLS LAST
                    LIMIT 1
                ) nxt ON TRUE
                WHERE cm.student_id = CAST(:student_id AS uuid)
                  AND upper(cm.status) = 'ACTIVE'
                  AND c.status = 'ACTIVE'
                ORDER BY (live.session_id IS NULL), cm.joined_at DESC
                """
            ),
            {"student_id": student["id"]},
        ).mappings().all()

        def iso(value):
            return value.isoformat() if value else None

        return jsonify(
            {
                "classes": [
                    {
                        "id": r["id"],
                        "code": r["code"],
                        "name": r["name"],
                        "lecturerName": r["lecturerName"],
                        "status": "ongoing" if r["liveSessionId"] else "upcoming",
                        "liveSession": (
                            {
                                "id": r["liveSessionId"],
                                "title": r["liveSessionTitle"],
                                "startedAt": iso(r["liveStartedAt"]),
                            }
                            if r["liveSessionId"]
                            else None
                        ),
                        "nextStartTime": iso(r["nextStartTime"]),
                        # Buổi sắp/đang đến giờ nhưng giảng viên chưa bấm bắt đầu -> "phòng chờ"
                        "nextSession": (
                            {
                                "id": r["nextSessionId"],
                                "title": r["nextSessionTitle"],
                                "startTime": iso(r["nextStartTime"]),
                                "endTime": iso(r["nextEndTime"]),
                            }
                            if r["nextSessionId"]
                            else None
                        ),
                    }
                    for r in rows
                ]
            }
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to list student classes")
        return jsonify({"message": "Không thể tải danh sách lớp."}), 500


# ----------------------------------------------------------------------
# Phiên học (session) mà sinh viên đang vào: thông tin, điểm danh vào/ra
# ----------------------------------------------------------------------
def _parse_session_id(raw):
    try:
        return str(UUID(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _member_session(session_id, student_id):
    """Phiên học nếu sinh viên là thành viên ACTIVE của lớp ACTIVE; ngược lại None."""
    return db.session.execute(
        text(
            """
            SELECT
                s.session_id::text AS id,
                s.session_title AS title,
                s.status,
                s.delivery_mode AS "deliveryMode",
                s.started_at AS "startedAt",
                c.class_id::text AS "classId",
                c.class_code AS "classCode",
                c.class_name AS "className",
                l.full_name AS "lecturerName"
            FROM sessions s
            JOIN classes c ON c.class_id = s.class_id
            JOIN lecturers l ON l.lecturer_id = c.lecturer_id
            WHERE s.session_id = CAST(:session_id AS uuid)
              AND c.status = 'ACTIVE'
              AND EXISTS (
                  SELECT 1 FROM class_members cm
                  WHERE cm.class_id = c.class_id
                    AND cm.student_id = CAST(:student_id AS uuid)
                    AND upper(cm.status) = 'ACTIVE'
              )
            """
        ),
        {"session_id": session_id, "student_id": student_id},
    ).mappings().first()


# Phiên đã kết thúc/bị huỷ: không vào (lại) được. Cùng mã với /auth/sessions/<id>/access.
CLOSED_SESSION_STATUSES = frozenset({"ENDED", "CANCELLED"})


def _closed_session_response(row):
    """403 session_closed nếu phiên đã đóng, ngược lại None."""
    if str(row["status"] or "").upper() not in CLOSED_SESSION_STATUSES:
        return None
    return jsonify({
        "message": "Phiên học đã kết thúc hoặc bị huỷ.",
        "code": "session_closed",
    }), 403


def _session_payload(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "deliveryMode": row["deliveryMode"],
        "startedAt": row["startedAt"].isoformat() if row["startedAt"] else None,
        "class": {
            "id": row["classId"],
            "code": row["classCode"],
            "name": row["className"],
        },
        "lecturerName": row["lecturerName"],
    }


@student_sessions_bp.route("/<session_id>", methods=["GET"])
@jwt_required()
def get_session(session_id):
    normalized = _parse_session_id(session_id)
    if not normalized:
        return jsonify({"message": "Mã phiên học không hợp lệ."}), 400
    # Giữ thứ tự cũ: kiểm tra dữ liệu đầu vào trước, rồi mới kiểm tra vai trò.
    denied = role_denied(*STUDENT_ROLES, message="Chỉ sinh viên mới xem được phiên học.")
    if denied:
        return denied
    try:
        student = _current_student()
        if not student:
            return jsonify({"message": "Chỉ sinh viên mới xem được phiên học."}), 403
        row = _member_session(normalized, student["id"])
        # Cùng một thông báo cho "không tồn tại" và "chưa tham gia lớp"
        if not row:
            return jsonify({"message": "Không tìm thấy phiên học hoặc bạn chưa tham gia lớp này."}), 404
        closed = _closed_session_response(row)
        if closed:
            return closed
        return jsonify({"session": _session_payload(row)})
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to load student session")
        return jsonify({"message": "Không thể tải phiên học."}), 500


@student_sessions_bp.route("/<session_id>/join", methods=["POST"])
@jwt_required()
def join_session(session_id):
    """Điểm danh vào phiên (chỉ khi phiên đang LIVE). Gọi nhiều lần vẫn an toàn."""
    normalized = _parse_session_id(session_id)
    if not normalized:
        return jsonify({"message": "Mã phiên học không hợp lệ."}), 400
    # Giữ thứ tự cũ: kiểm tra dữ liệu đầu vào trước, rồi mới kiểm tra vai trò.
    denied = role_denied(*STUDENT_ROLES, message="Chỉ sinh viên mới vào được phiên học.")
    if denied:
        return denied
    try:
        student = _current_student()
        if not student:
            return jsonify({"message": "Chỉ sinh viên mới vào được phiên học."}), 403
        row = _member_session(normalized, student["id"])
        if not row:
            return jsonify({"message": "Không tìm thấy phiên học hoặc bạn chưa tham gia lớp này."}), 404
        closed = _closed_session_response(row)
        if closed:
            return closed
        if str(row["status"]).upper() != "LIVE":
            return jsonify({"message": "Buổi học chưa diễn ra.", "session": _session_payload(row)}), 409

        db.session.execute(
            text(
                """
                INSERT INTO student_sessions (
                    student_id, session_id, is_active, last_active_at, left_at
                ) VALUES (
                    CAST(:student_id AS uuid), CAST(:session_id AS uuid),
                    TRUE, NOW(), NULL
                )
                ON CONFLICT (student_id, session_id)
                DO UPDATE SET is_active = TRUE, last_active_at = NOW(), left_at = NULL
                """
            ),
            {"student_id": student["id"], "session_id": normalized},
        )
        db.session.commit()
        return jsonify({"success": True, "session": _session_payload(row)})
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Student session join failed")
        return jsonify({"message": "Không thể vào phiên học lúc này."}), 500


@student_sessions_bp.route("/<session_id>/leave", methods=["POST"])
@jwt_required()
def leave_session(session_id):
    normalized = _parse_session_id(session_id)
    if not normalized:
        return jsonify({"message": "Mã phiên học không hợp lệ."}), 400
    # Giữ thứ tự cũ: kiểm tra dữ liệu đầu vào trước, rồi mới kiểm tra vai trò.
    denied = role_denied(*STUDENT_ROLES, message="Chỉ sinh viên mới rời được phiên học.")
    if denied:
        return denied
    try:
        student = _current_student()
        if not student:
            return jsonify({"message": "Chỉ sinh viên mới rời được phiên học."}), 403
        db.session.execute(
            text(
                """
                UPDATE student_sessions
                SET is_active = FALSE, left_at = NOW(), last_active_at = NOW()
                WHERE student_id = CAST(:student_id AS uuid)
                  AND session_id = CAST(:session_id AS uuid)
                  AND is_active = TRUE
                """
            ),
            {"student_id": student["id"], "session_id": normalized},
        )
        db.session.commit()
        return jsonify({"success": True})
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Student session leave failed")
        return jsonify({"message": "Không thể rời phiên học lúc này."}), 500
