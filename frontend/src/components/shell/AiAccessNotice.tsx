"use client";

import { useSyncExternalStore } from "react";
import { clearAiAccessMessage, getAiAccessMessage, subscribeAiAccessMessage } from "../../lib/ai";

/** Thông báo lỗi phiên học/quyền vào phòng do aiFetch (lib/ai.ts) báo lên. */
export default function AiAccessNotice() {
  const message = useSyncExternalStore(subscribeAiAccessMessage, getAiAccessMessage, () => "");
  if (!message) return null;
  return (
    <div
      role="alert"
      style={{
        position: "fixed", top: 12, left: "50%", transform: "translateX(-50%)", zIndex: 1000,
        maxWidth: "calc(100vw - 32px)", display: "flex", alignItems: "center", gap: 12,
        background: "#7f1d1d", color: "#fee2e2", border: "1px solid #ef4444", borderRadius: 8,
        padding: "10px 14px", fontSize: 14, boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
      }}
    >
      <span>{message}</span>
      <button
        type="button"
        onClick={clearAiAccessMessage}
        aria-label="Đóng thông báo"
        style={{ background: "transparent", border: "none", color: "#fecaca", fontSize: 18, cursor: "pointer", lineHeight: 1 }}
      >
        ×
      </button>
    </div>
  );
}
