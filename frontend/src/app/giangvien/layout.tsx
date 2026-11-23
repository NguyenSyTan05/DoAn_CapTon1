"use client";

import type { ReactNode } from "react";
import { RoleGuard } from "../../lib/guards";

export default function LecturerRouteLayout({ children }: { children: ReactNode }) {
  return <RoleGuard roles={["giang_vien"]}>{() => children}</RoleGuard>;
}
