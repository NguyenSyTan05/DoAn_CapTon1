"use client";

import { aiWsUrl } from '../../../lib/ai';
import { useEffect, useState } from "react";
import styles from "./QAToast.module.css";

interface AnswerOutput {
  representative_id: string;
  representative_text: string;
  total_count: number;
  answer_text: string;
  answered_at: string;
}

interface ToastItem extends AnswerOutput {
  toastId: number;
}

const TOAST_DURATION_MS = 6000;

/**
 * [CUSTOM] Popup thông báo dùng chung cho MỌI người xem đang mở phòng —
 * giảng viên (app/page.tsx) lẫn sinh viên (student/page.tsx). Tự kết nối
 * /api/v1/ws/qa (xem be/service/qa_broadcast.py), độc lập với bất kỳ state
 * Q&A nào khác trên trang — chỉ hiện popup, không hiện danh sách câu hỏi
 * hay ô nhập trả lời (những thứ đó đã chuyển hẳn sang Dashboard Giảng viên).
 *
 * Chỉ popup cho câu trả lời MỚI phát sinh SAU khi đã kết nối — "snapshot"
 * ban đầu (các câu đã trả lời từ trước) không kích hoạt popup, tránh dội
 * một loạt thông báo cũ ngay khi vừa vào phòng.
 */
export default function QAToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    const wsUrl = aiWsUrl("/api/v1/ws/qa");
    const ws = new WebSocket(wsUrl);
    let hasSnapshot = false;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "snapshot") {
          hasSnapshot = true;
        } else if (msg.type === "upsert" && hasSnapshot) {
          const toastId = Date.now();
          setToasts((prev) => [...prev, { ...msg.answer, toastId }]);
          setTimeout(() => {
            setToasts((prev) => prev.filter((t) => t.toastId !== toastId));
          }, TOAST_DURATION_MS);
        }
      } catch (err) {
        console.warn("QAToast parse error:", err);
      }
    };

    return () => ws.close();
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className={styles.container}>
      {toasts.map((toast) => (
        <div key={toast.toastId} className={styles.toast}>
          <div className={styles.badge}>
            {toast.total_count} asked · New answer
          </div>
          <div className={styles.question}>{toast.representative_text}</div>
          <div className={styles.answer}>{toast.answer_text}</div>
        </div>
      ))}
    </div>
  );
}
