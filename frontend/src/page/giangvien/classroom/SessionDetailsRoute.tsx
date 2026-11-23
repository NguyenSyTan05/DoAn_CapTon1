"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import LecturerLayout from "../layoutGV";
import ChiTietPhienHoc from "./chitiet";

type Status = NonNullable<React.ComponentProps<typeof ChiTietPhienHoc>["initialStatus"]>;

export default function SessionDetailsRoute() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const router = useRouter();
  const status = (useSearchParams().get("status") ?? "upcoming") as Status;

  return (
    <LecturerLayout>
      <ChiTietPhienHoc
        sessionId={sessionId}
        initialStatus={status}
        onBack={() => router.push("/giangvien/classroom")}
      />
    </LecturerLayout>
  );
}
