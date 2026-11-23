"use client";

import type { ReactNode } from "react";
import { RoleGuard } from "../../lib/guards";
import Layout from "../../components/shell/layout";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <RoleGuard roles={["admin"]}>
      {(user) => <Layout user={user}>{children}</Layout>}
    </RoleGuard>
  );
}
