"use client";

import { useEffect, useRef, useState } from "react";
import studentService from "../../services/student.service";

export interface SessionInfo {
  id: string;
  title: string;
  status: string; // LIVE | SCHEDULED | ENDED | CANCELLED
  startedAt: string | null;
  class: { id: string; code: string; name: string };
  lecturerName: string;
}

/**
 * Phiên học mà sinh viên đang vào:
 *  - tải thông tin phiên (lỗi nếu chưa là thành viên lớp);
 *  - điểm danh khi phiên LIVE và ghi nhận rời lớp khi thoát trang;
 *  - "phòng chờ": phiên SCHEDULED được hỏi lại mỗi 8 giây cho tới khi giảng viên bắt đầu.
 */
export function useStudentSession(sessionId: string | null, enabled: boolean) {
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const joinedRef = useRef(false);

  useEffect(() => {
    if (!enabled || !sessionId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const session: SessionInfo = await studentService.getSession(sessionId);
        if (cancelled) return;
        setInfo(session);
        if (session.status === "LIVE") {
          await studentService.joinSession(sessionId);
          joinedRef.current = true;
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(
            err.response?.data?.message ||
              (err.response ? "Không thể tải phiên học." : "Không kết nối được máy chủ."),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (joinedRef.current) {
        joinedRef.current = false;
        void studentService.leaveSession(sessionId).catch(() => {});
      }
    };
  }, [sessionId, enabled]);

  useEffect(() => {
    if (!enabled || !sessionId || info?.status !== "SCHEDULED") return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const fresh: SessionInfo = await studentService.getSession(sessionId);
        if (stopped) return;
        setInfo(fresh);
        if (fresh.status === "LIVE") {
          await studentService.joinSession(sessionId);
          joinedRef.current = true;
        }
      } catch (err) {
        // Phiên bị huỷ trong lúc chờ -> báo lỗi; lỗi khác: thử lại ở lượt sau
        const data = (err as { response?: { data?: { code?: string; message?: string } } }).response?.data;
        if (!stopped && data?.code === "session_closed") {
          setError(data.message || "Phiên học đã kết thúc hoặc bị huỷ.");
        }
      }
    }, 8000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [sessionId, enabled, info?.status]);

  return { info, loading, error };
}
