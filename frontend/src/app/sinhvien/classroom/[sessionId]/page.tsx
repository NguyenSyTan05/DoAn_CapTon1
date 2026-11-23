import { redirect } from "next/navigation";

// Sinh viên vào phòng học bằng giao diện máy tính /room (cùng giao diện với giảng viên)
export default async function Page({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  redirect(`/room?session=${encodeURIComponent(sessionId)}`);
}
