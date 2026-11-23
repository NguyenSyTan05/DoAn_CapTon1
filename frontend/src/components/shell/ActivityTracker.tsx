"use client";

import { useEffect } from "react";
import api from "../../services/api";

export default function ActivityTracker() {
  useEffect(() => {
    function recordClick(event: MouseEvent) {
      const clicked = event.target instanceof Element ? event.target : null;
      if (!clicked) return;
      const element =
        clicked.closest(
          "button, a, input, select, textarea, label, summary, [role='button'], [role='link']",
        ) || clicked;
      const isFormField = element.matches("input, select, textarea");
      const label =
        element.getAttribute("aria-label") ||
        element.getAttribute("data-audit-label") ||
        element.getAttribute("title") ||
        (isFormField
          ? element.getAttribute("placeholder") || element.getAttribute("name")
          : (element as HTMLElement).innerText || element.textContent) ||
        "";

      void api
        .post("/auth/activity", {
          page: window.location.pathname,
          tag: element.tagName.toLowerCase(),
          label: label.trim().slice(0, 240),
          elementId: element.id || "",
        })
        .catch(() => {});
    }

    document.addEventListener("click", recordClick, true);
    return () => document.removeEventListener("click", recordClick, true);
  }, []);

  return null;
}
