-- =====================================================================
-- Migration 005: Bổ sung SQL Trigger tự cập nhật updated_at & Composite Index
-- Phục vụ tối ưu hiệu năng truy vấn nóng theo phiên học (PostgreSQL 15+)
-- =====================================================================

BEGIN;

CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'admins',
        'lecturers',
        'students',
        'classes',
        'class_schedules',
        'lesson_summaries',
        'student_notes',
        'question_groups',
        'answers',
        'chatbot_conversations',
        'session_statistics'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I;', tbl, tbl);
        EXECUTE format(
            'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();',
            tbl,
            tbl
        );
    END LOOP;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_questions_session_status
    ON questions(session_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_transcripts_session_lang
    ON transcripts(session_id, language, chunk_index);

COMMIT;
