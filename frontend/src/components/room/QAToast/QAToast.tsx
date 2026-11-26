"use client";

import { aiWsUrl } from "../../../lib/ai";
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

export default function QAToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    let active = true;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (!active) return;
      let hasSnapshot = false;
      ws = new WebSocket(aiWsUrl("/api/v1/ws/qa"));

      ws.onmessage = (event) => {
        if (!active) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "snapshot") {
            hasSnapshot = true;
          } else if (msg.type === "upsert" && hasSnapshot) {
            const toastId = Date.now() + Math.random();
            setToasts((prev) => [...prev, { ...msg.answer, toastId }]);
            setTimeout(() => {
              if (active) {
                setToasts((prev) => prev.filter((t) => t.toastId !== toastId));
              }
            }, TOAST_DURATION_MS);
          }
        } catch (err) {
          console.warn("QAToast parse error:", err);
        }
      };

      ws.onclose = (ev) => {
        if (!active || ev.code === 1008) return;
        reconnectTimer = setTimeout(connect, 3000);
      };
    };

    connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close();
      }
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className={styles.container}>
      {toasts.map((toast) => (
        <div key={toast.toastId} className={styles.toast}>
          <div className={styles.badge}>
            {toast.total_count} bạn hỏi tương tự · Câu trả lời mới
          </div>
          <div className={styles.question}>{toast.representative_text}</div>
          <div className={styles.answer}>{toast.answer_text}</div>
        </div>
      ))}
    </div>
  );
}
