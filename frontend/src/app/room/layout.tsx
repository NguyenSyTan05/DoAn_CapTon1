"use client";

import type { ReactNode } from "react";
import { RoleGuard } from "../../lib/guards";

export default function RoomLayout({ children }: { children: ReactNode }) {
  return <RoleGuard roles={["giang_vien", "sinh_vien", "student"]}>{() => children}</RoleGuard>;
}
