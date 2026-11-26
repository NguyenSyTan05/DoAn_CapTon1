"use client";

import { RoleGuard } from "../../lib/guards";
import LessonSummaryPage from "../../page/summary/LessonSummaryPage";

export default function StudentSummaryRoute() {
  return (
    <RoleGuard roles={["sinh_vien", "student", "giang_vien"]}>
      {() => <LessonSummaryPage mode="student" />}
    </RoleGuard>
  );
}
