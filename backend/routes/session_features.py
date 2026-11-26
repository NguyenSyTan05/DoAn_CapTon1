"""Các API mở rộng hoàn thiện luồng nghiệp vụ Phần 1 cho ClassBridge:
1. Danh sách phiên học phục vụ xem Tóm tắt bài giảng & Heatmap (`GET /auth/summaries/sessions`)
2. Sinh viên xem & trả lời Câu hỏi nhanh / Poll / Quiz (`GET/POST /auth/student/sessions/<id>/quick-questions...`)
3. Sinh viên & Giảng viên gửi Đánh giá sau buổi học (`GET/POST /auth/sessions/<id>/feedback`)
4. Giảng viên xem & cập nhật Hồ sơ cá nhân (`GET/PATCH /auth/lecturer/profile`)

Mọi endpoint đều kiểm tra JWT, vai trò và tư cách thành viên lớp học.
"""

from __future__ import annotations

import base64
import json
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from auth_utils import (
    LECTURER_REQUIRED_MESSAGE,
    LECTURER_ROLE,
    STUDENT_ROLES,
    role_required,
)
from extensions import db

session_features_bp = Blueprint("session_features", __name__, url_prefix="/auth")


def _parse_uuid(raw) -> str | None:
    try:
        return str(UUID(str(raw)))
    except (ValueError, TypeError, AttributeError):
        return None


def _iso(val):
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


def _active_lecturer_by_email(email: str):
    return db.session.execute(
        text(
            """
            SELECT lecturer_id::text AS id, full_name, email, phone, department, preferred_language
            FROM lecturers
            WHERE lower(email) = lower(:email) AND is_active = TRUE
            """
        ),
        {"email": email},
    ).mappings().first()


def _active_student_by_email(email: str):
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


# =====================================================================
# 1. Danh sách phiên học cho trang Tóm tắt bài giảng & Q&A Hub
# =====================================================================
@session_features_bp.route("/summaries/sessions", methods=["GET"])
@jwt_required()
def list_summary_sessions():
    role = get_jwt().get("role")
    email = get_jwt_identity()
    if not isinstance(email, str) or not email:
        return jsonify({"message": "Phiên đăng nhập không hợp lệ."}), 401

    try:
        if role == LECTURER_ROLE:
            lecturer = db.session.execute(
                text(
                    "SELECT lecturer_id::text AS id, full_name FROM lecturers "
                    "WHERE lower(email) = lower(:email) AND is_active = TRUE"
                ),
                {"email": email},
            ).mappings().first()
            if not lecturer:
                return jsonify({"message": LECTURER_REQUIRED_MESSAGE, "code": "role_forbidden"}), 403

            rows = db.session.execute(
                text(
                    """
                    SELECT
                        s.session_id::text AS id,
                        s.session_title AS title,
                        upper(s.status) AS status,
                        s.started_at AS "startedAt",
                        s.ended_at AS "endedAt",
                        c.class_code AS "classCode",
                        c.class_name AS "className"
                    FROM sessions s
                    JOIN classes c ON c.class_id = s.class_id
                    WHERE c.lecturer_id = CAST(:lecturer_id AS uuid)
                      AND c.status = 'ACTIVE'
                      AND upper(s.status) IN ('LIVE', 'ENDED', 'SCHEDULED')
                    ORDER BY
                        CASE upper(s.status)
                            WHEN 'LIVE' THEN 0
                            WHEN 'ENDED' THEN 1
                            ELSE 2
                        END,
                        s.started_at DESC
                    LIMIT 50
                    """
                ),
                {"lecturer_id": lecturer["id"]},
            ).mappings().all()

            return jsonify(
                {
                    "sessions": [
                        {
                            "id": r["id"],
                            "title": r["title"],
                            "status": r["status"],
                            "startedAt": _iso(r["startedAt"]),
                            "endedAt": _iso(r["endedAt"]),
                            "classCode": r["classCode"],
                            "className": r["className"],
                            "lecturerName": lecturer["full_name"],
                        }
                        for r in rows
                    ]
                }
            )

        if role in STUDENT_ROLES:
            student = _active_student_by_email(email)
            if not student:
                return jsonify({"message": "Chỉ sinh viên đang hoạt động mới truy cập được.", "code": "role_forbidden"}), 403

            rows = db.session.execute(
                text(
                    """
                    SELECT
                        s.session_id::text AS id,
                        s.session_title AS title,
                        upper(s.status) AS status,
                        s.started_at AS "startedAt",
                        s.ended_at AS "endedAt",
                        c.class_code AS "classCode",
                        c.class_name AS "className",
                        l.full_name AS "lecturerName"
                    FROM sessions s
                    JOIN classes c ON c.class_id = s.class_id
                    JOIN lecturers l ON l.lecturer_id = c.lecturer_id
                    JOIN class_members cm ON cm.class_id = c.class_id
                    WHERE cm.student_id = CAST(:student_id AS uuid)
                      AND upper(cm.status) = 'ACTIVE'
                      AND c.status = 'ACTIVE'
                      AND upper(s.status) IN ('LIVE', 'ENDED', 'SCHEDULED')
                    ORDER BY
                        CASE upper(s.status)
                            WHEN 'LIVE' THEN 0
                            WHEN 'ENDED' THEN 1
                            ELSE 2
                        END,
                        s.started_at DESC
                    LIMIT 50
                    """
                ),
                {"student_id": student["id"]},
            ).mappings().all()

            return jsonify(
                {
                    "sessions": [
                        {
                            "id": r["id"],
                            "title": r["title"],
                            "status": r["status"],
                            "startedAt": _iso(r["startedAt"]),
                            "endedAt": _iso(r["endedAt"]),
                            "classCode": r["classCode"],
                            "className": r["className"],
                            "lecturerName": r["lecturerName"],
                        }
                        for r in rows
                    ]
                }
            )

        return jsonify({"message": "Vai trò hiện tại không hỗ trợ danh sách này.", "code": "role_forbidden"}), 403
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to list summary sessions")
        return jsonify({"message": "Không thể tải danh sách phiên học."}), 500


# =====================================================================
# 2. Sinh viên xem & trả lời Câu hỏi nhanh (Quick Questions / Poll / Quiz)
# =====================================================================
def _student_member_session(session_id: str, student_id: str):
    return db.session.execute(
        text(
            """
            SELECT s.session_id::text AS id, upper(s.status) AS status
            FROM sessions s
            JOIN classes c ON c.class_id = s.class_id
            JOIN class_members cm ON cm.class_id = c.class_id
            WHERE s.session_id = CAST(:session_id AS uuid)
              AND c.status = 'ACTIVE'
              AND cm.student_id = CAST(:student_id AS uuid)
              AND upper(cm.status) = 'ACTIVE'
            """
        ),
        {"session_id": session_id, "student_id": student_id},
    ).mappings().first()


def _parse_json_field(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


@session_features_bp.route("/student/sessions/<session_id>/quick-questions", methods=["GET"])
@role_required(*STUDENT_ROLES, message="Chỉ sinh viên mới xem được câu hỏi nhanh.")
def student_list_quick_questions(session_id: str):
    norm_sid = _parse_uuid(session_id)
    if not norm_sid:
        return jsonify({"message": "Mã phiên học không hợp lệ."}), 400

    email = get_jwt_identity()
    try:
        student = _active_student_by_email(email) if isinstance(email, str) else None
        if not student:
            return jsonify({"message": "Không tìm thấy tài khoản sinh viên."}), 403

        sess = _student_member_session(norm_sid, student["id"])
        if not sess:
            return jsonify({"message": "Không tìm thấy phiên học hoặc bạn chưa tham gia lớp này."}), 404
        if sess["status"] == "CANCELLED":
            return jsonify({"message": "Phiên học đã bị huỷ.", "code": "session_closed"}), 403

        q_rows = db.session.execute(
            text(
                """
                SELECT
                    q.quick_question_id::text AS id,
                    q.question_text AS question,
                    q.question_type AS "questionType",
                    q.question_payload AS payload,
                    q.created_at AS "createdAt",
                    o.option_id::text AS option_id,
                    o.option_text AS option_text,
                    o.is_correct AS is_correct,
                    o.option_order AS option_order,
                    o.image_data AS image_data,
                    o.image_mime_type AS image_mime_type
                FROM quick_questions q
                LEFT JOIN quick_question_options o
                    ON o.quick_question_id = q.quick_question_id
                WHERE q.session_id = CAST(:session_id AS uuid)
                ORDER BY q.created_at DESC, o.option_order ASC
                """
            ),
            {"session_id": norm_sid},
        ).mappings().all()

        resp_rows = db.session.execute(
            text(
                """
                SELECT
                    r.quick_question_id::text AS qid,
                    r.selected_option_id::text AS "selectedOptionId",
                    r.answer_text AS "answerText",
                    r.is_correct AS "isCorrect",
                    r.submitted_at AS "submittedAt"
                FROM quick_question_responses r
                JOIN student_sessions ss ON ss.student_session_id = r.student_session_id
                WHERE ss.session_id = CAST(:session_id AS uuid)
                  AND ss.student_id = CAST(:student_id AS uuid)
                """
            ),
            {"session_id": norm_sid, "student_id": student["id"]},
        ).mappings().all()
        responses_by_qid = {
            r["qid"]: {
                "selectedOptionId": r["selectedOptionId"],
                "answerText": r["answerText"],
                "isCorrect": r["isCorrect"],
                "submittedAt": _iso(r["submittedAt"]),
            }
            for r in resp_rows
        }

        grouped: dict[str, dict] = {}
        for row in q_rows:
            qid = row["id"]
            my_resp = responses_by_qid.get(qid)
            already_answered = my_resp is not None
            if qid not in grouped:
                raw_payload = _parse_json_field(row["payload"])
                public_payload: dict = {}
                if row["questionType"] == "MATCHING" and isinstance(raw_payload.get("pairs"), list):
                    pairs = raw_payload["pairs"]
                    public_payload["leftItems"] = [p.get("left", "") for p in pairs if isinstance(p, dict)]
                    # Đảo thứ tự theo bảng chữ cái để không lộ đáp án nối đôi trước khi nộp
                    public_payload["rightItems"] = sorted(
                        [p.get("right", "") for p in pairs if isinstance(p, dict)]
                    )
                    if already_answered:
                        public_payload["pairs"] = pairs
                elif row["questionType"] == "ORDERING" and already_answered:
                    public_payload["correctOrder"] = raw_payload.get("correctOrder", [])

                grouped[qid] = {
                    "id": qid,
                    "question": row["question"],
                    "questionType": row["questionType"],
                    "payload": public_payload,
                    "createdAt": _iso(row["createdAt"]),
                    "options": [],
                    "myResponse": my_resp,
                }
            if row["option_id"] is not None:
                img_url = None
                if row["image_data"] and row["image_mime_type"]:
                    b64 = base64.b64encode(bytes(row["image_data"])).decode("ascii")
                    img_url = f"data:{row['image_mime_type']};base64,{b64}"
                grouped[qid]["options"].append(
                    {
                        "id": row["option_id"],
                        "text": row["option_text"],
                        "imageDataUrl": img_url,
                        # Chỉ tiết lộ đáp án đúng SAU KHI sinh viên đã nộp bài
                        "isCorrect": bool(row["is_correct"]) if already_answered else None,
                    }
                )

        # Với câu ORDERING chưa trả lời, xáo trộn thứ tự hiển thị theo bảng chữ cái để không lộ thứ tự gốc
        for item in grouped.values():
            if item["questionType"] == "ORDERING" and item["myResponse"] is None:
                item["options"] = sorted(item["options"], key=lambda o: o["text"].casefold())

        return jsonify({"questions": list(grouped.values())})
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to list student quick questions")
        return jsonify({"message": "Không thể tải câu hỏi nhanh."}), 500


@session_features_bp.route(
    "/student/sessions/<session_id>/quick-questions/<question_id>/respond",
    methods=["POST"],
)
@role_required(*STUDENT_ROLES, message="Chỉ sinh viên mới gửi được câu trả lời.")
def student_respond_quick_question(session_id: str, question_id: str):
    norm_sid = _parse_uuid(session_id)
    norm_qid = _parse_uuid(question_id)
    if not norm_sid or not norm_qid:
        return jsonify({"message": "Mã phiên học hoặc câu hỏi không hợp lệ."}), 400

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"message": "Dữ liệu gửi lên không hợp lệ."}), 400

    email = get_jwt_identity()
    try:
        student = _active_student_by_email(email) if isinstance(email, str) else None
        if not student:
            return jsonify({"message": "Không tìm thấy tài khoản sinh viên."}), 403

        sess = _student_member_session(norm_sid, student["id"])
        if not sess:
            return jsonify({"message": "Không tìm thấy phiên học hoặc bạn chưa tham gia lớp này."}), 404
        if sess["status"] != "LIVE":
            return jsonify({"message": "Chỉ có thể trả lời khi buổi học đang diễn ra trực tiếp."}), 409

        q_row = db.session.execute(
            text(
                """
                SELECT quick_question_id::text AS id, question_type, question_payload
                FROM quick_questions
                WHERE quick_question_id = CAST(:qid AS uuid)
                  AND session_id = CAST(:session_id AS uuid)
                """
            ),
            {"qid": norm_qid, "session_id": norm_sid},
        ).mappings().first()
        if not q_row:
            return jsonify({"message": "Không tìm thấy câu hỏi trong buổi học này."}), 404

        q_type = q_row["question_type"]
        payload = _parse_json_field(q_row["question_payload"])

        selected_option_id: str | None = None
        answer_text: str | None = None
        is_correct: bool | None = None

        if q_type in ("POLL", "MULTIPLE_CHOICE", "TRUE_FALSE"):
            opt_id = _parse_uuid(body.get("selectedOptionId"))
            if not opt_id:
                return jsonify({"message": "Vui lòng chọn một phương án trả lời."}), 400
            opt_row = db.session.execute(
                text(
                    """
                    SELECT option_id::text AS id, option_text, is_correct
                    FROM quick_question_options
                    WHERE option_id = CAST(:oid AS uuid)
                      AND quick_question_id = CAST(:qid AS uuid)
                    """
                ),
                {"oid": opt_id, "qid": norm_qid},
            ).mappings().first()
            if not opt_row:
                return jsonify({"message": "Phương án đã chọn không thuộc câu hỏi này."}), 400
            selected_option_id = opt_row["id"]
            answer_text = opt_row["option_text"]
            is_correct = None if q_type == "POLL" else bool(opt_row["is_correct"])

        elif q_type == "SHORT_ANSWER":
            raw_ans = body.get("answerText")
            if not isinstance(raw_ans, str) or not raw_ans.strip():
                return jsonify({"message": "Vui lòng nhập câu trả lời."}), 400
            answer_text = raw_ans.strip()[:1000]
            is_correct = None

        elif q_type == "ORDERING":
            ordered = body.get("orderedItems")
            correct_order = [str(x).strip() for x in (payload.get("correctOrder") or []) if str(x).strip()]
            if not isinstance(ordered, list) or len(correct_order) < 2 or len(ordered) != len(correct_order):
                return jsonify({"message": "Danh sách thứ tự trả lời chưa đầy đủ."}), 400
            cleaned_order = [str(x).strip() for x in ordered]
            expected_folded = [x.casefold() for x in correct_order]
            actual_folded = [x.casefold() for x in cleaned_order]
            if sorted(actual_folded) != sorted(expected_folded):
                return jsonify({"message": "Các mục sắp xếp không khớp với đề bài."}), 400
            answer_text = json.dumps(cleaned_order, ensure_ascii=False)
            is_correct = actual_folded == expected_folded

        elif q_type == "MATCHING":
            submitted_pairs = body.get("pairs")
            correct_pairs = payload.get("pairs") or []
            if (
                not isinstance(submitted_pairs, list)
                or len(correct_pairs) < 2
                or len(submitted_pairs) != len(correct_pairs)
                or any(not isinstance(p, dict) for p in submitted_pairs)
            ):
                return jsonify({"message": "Vui lòng nối đầy đủ tất cả các cặp."}), 400
            expected_map = {
                str(p.get("left", "")).strip().casefold(): str(p.get("right", "")).strip().casefold()
                for p in correct_pairs
                if isinstance(p, dict)
            }
            valid_rights = set(expected_map.values())
            actual_map: dict[str, str] = {}
            for p in submitted_pairs:
                l_val = str(p.get("left", "")).strip().casefold()
                r_val = str(p.get("right", "")).strip().casefold()
                if not l_val or not r_val or l_val not in expected_map or r_val not in valid_rights:
                    return jsonify({"message": "Cặp nối không hợp lệ so với đề bài."}), 400
                actual_map[l_val] = r_val
            if len(actual_map) != len(expected_map):
                return jsonify({"message": "Mỗi mục bên trái chỉ được nối một lần."}), 400
            answer_text = json.dumps(submitted_pairs, ensure_ascii=False)
            is_correct = actual_map == expected_map

        # Đảm bảo đã có dòng student_sessions cho sinh viên trong phiên LIVE
        ss_row = db.session.execute(
            text(
                """
                SELECT student_session_id::text AS id
                FROM student_sessions
                WHERE student_id = CAST(:student_id AS uuid)
                  AND session_id = CAST(:session_id AS uuid)
                """
            ),
            {"student_id": student["id"], "session_id": norm_sid},
        ).mappings().first()
        if ss_row:
            student_session_id = ss_row["id"]
        else:
            db.session.execute(
                text(
                    """
                    INSERT INTO student_sessions (student_id, session_id, is_active)
                    VALUES (CAST(:student_id AS uuid), CAST(:session_id AS uuid), TRUE)
                    ON CONFLICT (student_id, session_id) DO UPDATE SET is_active = TRUE
                    """
                ),
                {"student_id": student["id"], "session_id": norm_sid},
            )
            ss_row = db.session.execute(
                text(
                    """
                    SELECT student_session_id::text AS id
                    FROM student_sessions
                    WHERE student_id = CAST(:student_id AS uuid)
                      AND session_id = CAST(:session_id AS uuid)
                    """
                ),
                {"student_id": student["id"], "session_id": norm_sid},
            ).mappings().first()
            if not ss_row:
                raise SQLAlchemyError("Missing student_session row after upsert")
            student_session_id = ss_row["id"]

        db.session.execute(
            text(
                """
                INSERT INTO quick_question_responses (
                    quick_question_id, student_session_id, selected_option_id, answer_text, is_correct, submitted_at
                ) VALUES (
                    CAST(:qid AS uuid),
                    CAST(:ssid AS uuid),
                    CAST(:oid AS uuid),
                    :answer_text,
                    :is_correct,
                    NOW()
                )
                ON CONFLICT (quick_question_id, student_session_id)
                DO UPDATE SET
                    selected_option_id = EXCLUDED.selected_option_id,
                    answer_text = EXCLUDED.answer_text,
                    is_correct = EXCLUDED.is_correct,
                    submitted_at = NOW()
                """
            ),
            {
                "qid": norm_qid,
                "ssid": student_session_id,
                "oid": selected_option_id,
                "answer_text": answer_text,
                "is_correct": is_correct,
            },
        )
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "response": {
                    "selectedOptionId": selected_option_id,
                    "answerText": answer_text,
                    "isCorrect": is_correct,
                },
            }
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to submit quick question response")
        return jsonify({"message": "Không thể lưu câu trả lời lúc này."}), 500


# =====================================================================
# 3. Đánh giá & Phản hồi buổi học (`session_feedback`)
# =====================================================================
@session_features_bp.route("/sessions/<session_id>/feedback", methods=["POST"])
@jwt_required()
def submit_session_feedback(session_id: str):
    norm_sid = _parse_uuid(session_id)
    if not norm_sid:
        return jsonify({"message": "Mã phiên học không hợp lệ."}), 400

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"message": "Dữ liệu đánh giá không hợp lệ."}), 400

    rating = body.get("rating")
    comment = (body.get("comment") or "").strip()
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        return jsonify({"message": "Điểm đánh giá phải từ 1 đến 5 sao."}), 400
    if len(comment) > 1000:
        return jsonify({"message": "Nhận xét tối đa 1000 ký tự."}), 400

    role = get_jwt().get("role")
    email = get_jwt_identity()
    if not isinstance(email, str) or not email:
        return jsonify({"message": "Phiên đăng nhập không hợp lệ."}), 401

    try:
        if role in STUDENT_ROLES:
            student = _active_student_by_email(email)
            if not student:
                return jsonify({"message": "Không tìm thấy tài khoản sinh viên."}), 403
            sess = _student_member_session(norm_sid, student["id"])
            if not sess:
                return jsonify({"message": "Bạn không thuộc lớp của phiên học này."}), 403
            if sess["status"] == "CANCELLED":
                return jsonify({"message": "Phiên học đã bị huỷ.", "code": "session_closed"}), 403
            if sess["status"] == "SCHEDULED":
                return jsonify({"message": "Buổi học chưa bắt đầu nên chưa thể gửi đánh giá."}), 409

            final_comment = comment or f"Đánh giá {rating}/5 sao"
            existing_fb = db.session.execute(
                text(
                    """
                    SELECT feedback_id
                    FROM session_feedback
                    WHERE session_id = CAST(:session_id AS uuid)
                      AND student_id = CAST(:student_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"session_id": norm_sid, "student_id": student["id"]},
            ).first()
            if existing_fb:
                db.session.execute(
                    text(
                        """
                        UPDATE session_feedback
                        SET rating = :rating, feedback_text = :comment, created_at = NOW()
                        WHERE feedback_id = :fid
                        """
                    ),
                    {"rating": rating, "comment": final_comment, "fid": existing_fb[0]},
                )
            else:
                db.session.execute(
                    text(
                        """
                        INSERT INTO session_feedback (
                            session_id, student_id, respondent_role, rating, feedback_text
                        ) VALUES (
                            CAST(:session_id AS uuid), CAST(:student_id AS uuid), 'STUDENT', :rating, :comment
                        )
                        """
                    ),
                    {
                        "session_id": norm_sid,
                        "student_id": student["id"],
                        "rating": rating,
                        "comment": final_comment,
                    },
                )
            db.session.commit()
            return jsonify({"success": True, "message": "Cảm ơn bạn đã gửi đánh giá buổi học!"}), 201

        if role == LECTURER_ROLE:
            lecturer = db.session.execute(
                text(
                    """
                    SELECT l.lecturer_id::text AS id, upper(s.status) AS status
                    FROM lecturers l
                    JOIN classes c ON c.lecturer_id = l.lecturer_id
                    JOIN sessions s ON s.class_id = c.class_id
                    WHERE lower(l.email) = lower(:email)
                      AND l.is_active = TRUE
                      AND c.status = 'ACTIVE'
                      AND s.session_id = CAST(:session_id AS uuid)
                    """
                ),
                {"email": email, "session_id": norm_sid},
            ).mappings().first()
            if not lecturer:
                return jsonify({"message": "Bạn không sở hữu phiên học này."}), 403
            if lecturer["status"] == "CANCELLED":
                return jsonify({"message": "Phiên học đã bị huỷ.", "code": "session_closed"}), 403
            if lecturer["status"] == "SCHEDULED":
                return jsonify({"message": "Buổi học chưa bắt đầu nên chưa thể gửi đánh giá."}), 409

            final_comment = comment or f"Ghi chú tự đánh giá phiên học ({rating}/5)"
            existing_fb = db.session.execute(
                text(
                    """
                    SELECT feedback_id
                    FROM session_feedback
                    WHERE session_id = CAST(:session_id AS uuid)
                      AND lecturer_id = CAST(:lecturer_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"session_id": norm_sid, "lecturer_id": lecturer["id"]},
            ).first()
            if existing_fb:
                db.session.execute(
                    text(
                        """
                        UPDATE session_feedback
                        SET rating = :rating, feedback_text = :comment, created_at = NOW()
                        WHERE feedback_id = :fid
                        """
                    ),
                    {"rating": rating, "comment": final_comment, "fid": existing_fb[0]},
                )
            else:
                db.session.execute(
                    text(
                        """
                        INSERT INTO session_feedback (
                            session_id, lecturer_id, respondent_role, rating, feedback_text
                        ) VALUES (
                            CAST(:session_id AS uuid), CAST(:lecturer_id AS uuid), 'LECTURER', :rating, :comment
                        )
                        """
                    ),
                    {
                        "session_id": norm_sid,
                        "lecturer_id": lecturer["id"],
                        "rating": rating,
                        "comment": final_comment,
                    },
                )
            db.session.commit()
            return jsonify({"success": True, "message": "Đã lưu phản hồi phiên học."}), 201

        return jsonify({"message": "Vai trò hiện tại không hỗ trợ gửi phản hồi.", "code": "role_forbidden"}), 403
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to submit session feedback")
        return jsonify({"message": "Không thể gửi đánh giá lúc này."}), 500


# =====================================================================
# 4. Hồ sơ cá nhân Giảng viên (`/giangvien/profile`)
# =====================================================================
@session_features_bp.route("/lecturer/profile", methods=["GET"])
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def get_lecturer_profile():
    email = get_jwt_identity()
    try:
        row = _active_lecturer_by_email(email) if isinstance(email, str) else None
        if not row:
            return jsonify({"message": LECTURER_REQUIRED_MESSAGE}), 403
        return jsonify(
            {
                "profile": {
                    "id": row["id"],
                    "fullName": row["full_name"],
                    "email": row["email"],
                    "phone": row["phone"] or "",
                    "department": row["department"] or "",
                    "preferredLanguage": row["preferred_language"] or "vi",
                }
            }
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to read lecturer profile")
        return jsonify({"message": "Không thể tải hồ sơ giảng viên."}), 500


@session_features_bp.route("/lecturer/profile", methods=["PATCH"])
@role_required(LECTURER_ROLE, message=LECTURER_REQUIRED_MESSAGE)
def update_lecturer_profile():
    email = get_jwt_identity()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"message": "Dữ liệu cập nhật không hợp lệ."}), 400

    full_name = str(body.get("fullName") or "").strip()
    phone = str(body.get("phone") or "").strip() or None
    department = str(body.get("department") or "").strip() or None
    preferred_language = str(body.get("preferredLanguage") or "vi").strip().lower()

    if not full_name or len(full_name) > 100:
        return jsonify({"message": "Họ và tên bắt buộc, tối đa 100 ký tự."}), 400
    if phone and len(phone) > 30:
        return jsonify({"message": "Số điện thoại tối đa 30 ký tự."}), 400
    if department and len(department) > 150:
        return jsonify({"message": "Khoa/Bộ môn tối đa 150 ký tự."}), 400
    if preferred_language not in ("vi", "en"):
        return jsonify({"message": "Ngôn ngữ ưu tiên chỉ nhận 'vi' hoặc 'en'."}), 400

    try:
        row = _active_lecturer_by_email(email) if isinstance(email, str) else None
        if not row:
            return jsonify({"message": LECTURER_REQUIRED_MESSAGE}), 403

        db.session.execute(
            text(
                """
                UPDATE lecturers
                SET full_name = :full_name,
                    phone = :phone,
                    department = :department,
                    preferred_language = :preferred_language,
                    updated_at = NOW()
                WHERE lecturer_id = CAST(:lecturer_id AS uuid)
                """
            ),
            {
                "full_name": full_name,
                "phone": phone,
                "department": department,
                "preferred_language": preferred_language,
                "lecturer_id": row["id"],
            },
        )
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "message": "Đã cập nhật hồ sơ cá nhân thành công.",
                "profile": {
                    "id": row["id"],
                    "fullName": full_name,
                    "email": row["email"],
                    "phone": phone or "",
                    "department": department or "",
                    "preferredLanguage": preferred_language,
                },
            }
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to update lecturer profile")
        return jsonify({"message": "Không thể cập nhật hồ sơ (kiểm tra trùng số điện thoại)."}), 409
