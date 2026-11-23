"use client";

import type { ReactNode } from "react";
import { RoleGuard } from "../../lib/guards";

export default function StudentLayout({ children }: { children: ReactNode }) {
  return <RoleGuard roles={["sinh_vien", "student"]}>{() => children}</RoleGuard>;
}
