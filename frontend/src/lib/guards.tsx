"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

type StoredUser = { role?: string; full_name?: string; email?: string };

/** Chỉ render children khi đã đăng nhập đúng vai trò; ngược lại chuyển về /login. */
export function RoleGuard({
  roles,
  children,
}: {
  roles: string[];
  children: (user: StoredUser) => ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<StoredUser | null>(null);
  const roleKey = roles.join(",");

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem("user") || "null");
      const token = localStorage.getItem("token");
      if (stored && token && roleKey.split(",").includes(stored.role)) {
        setUser(stored);
        return;
      }
    } catch {
      /* dữ liệu hỏng -> coi như chưa đăng nhập */
    }
    router.replace("/login");
  }, [roleKey, router]);

  return user ? <>{children(user)}</> : null;
}
