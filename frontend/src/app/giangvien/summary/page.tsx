"use client";

import LecturerLayout from "../../../page/giangvien/layoutGV";
import LessonSummaryPage from "../../../page/summary/LessonSummaryPage";

export default function LecturerSummaryRoute() {
  return (
    <LecturerLayout>
      <LessonSummaryPage mode="lecturer" />
    </LecturerLayout>
  );
}
