"use client";

import { notFound, useParams } from "next/navigation";
import LecturerLayout from "./layoutGV";

const SECTIONS: Record<string, { title: string; description: string }> = {
  sessions: { title: "Classroom Sessions", description: "Danh sách và trạng thái các phiên học." },
  qna: { title: "Anonymous Q&A", description: "Câu hỏi ẩn danh của sinh viên trong phiên học." },
  clusters: { title: "Question Clusters", description: "Các nhóm câu hỏi được AI gom theo chủ đề." },
  answers: { title: "Câu trả lời", description: "Kho câu trả lời của giảng viên cho các nhóm câu hỏi." },
  summary: { title: "Session Summary & Heatmap", description: "Tóm tắt bài giảng và bản đồ nhiệt tương tác của lớp." },
  profile: { title: "Hồ sơ cá nhân", description: "Thông tin tài khoản giảng viên." },
};

export default function SectionPlaceholder() {
  const { section } = useParams<{ section: string }>();
  const info = SECTIONS[section];
  if (!info) notFound();

  return (
    <LecturerLayout>
      <main style={{ flex: 1, minWidth: 0, padding: "28px 32px", background: "#f4f6fb" }}>
        <h1>{info.title}</h1>
        <p>{info.description}</p>
        <section
          style={{
            maxWidth: 640,
            marginTop: 24,
            padding: 20,
            background: "#fff",
            border: "1px solid #e7eaf3",
            borderRadius: 14,
          }}
        >
          Khu vực này đang được xây dựng.
        </section>
      </main>
    </LecturerLayout>
  );
}
