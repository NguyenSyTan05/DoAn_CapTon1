"use client";

/**
 * Lớp tương thích react-router-dom -> Next.js App Router.
 * Dùng khi chuyển các trang cũ (Vite) sang Next.js để không phải sửa từng
 * dòng Link/useNavigate. Về lâu dài có thể thay dần bằng next/link và
 * next/navigation trực tiếp.
 */
import NextLink from "next/link";
import {
  useParams as useNextParams,
  usePathname,
  useRouter,
} from "next/navigation";
import { useCallback, useEffect, type ComponentProps, type ReactNode } from "react";

type LinkProps = Omit<ComponentProps<typeof NextLink>, "href"> & { to: string };

export function Link({ to, ...rest }: LinkProps) {
  return <NextLink href={to} {...rest} />;
}

type NavLinkProps = Omit<LinkProps, "className" | "children"> & {
  end?: boolean;
  className?: string | ((state: { isActive: boolean }) => string);
  children?: ReactNode;
};

export function NavLink({ to, end, className, children, ...rest }: NavLinkProps) {
  const pathname = usePathname();
  const isActive = end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
  const resolved = typeof className === "function" ? className({ isActive }) : className;
  return (
    <NextLink href={to} className={resolved} {...rest}>
      {children}
    </NextLink>
  );
}

export function useNavigate() {
  const router = useRouter();
  return useCallback(
    (to: string | number, options?: { replace?: boolean }) => {
      if (typeof to === "number") {
        router.back();
      } else if (options?.replace) {
        router.replace(to);
      } else {
        router.push(to);
      }
    },
    [router],
  );
}

export function useLocation() {
  return { pathname: usePathname() };
}

export function useParams<T extends Record<string, string | undefined> = Record<string, string | undefined>>() {
  return useNextParams() as unknown as T;
}

export function Navigate({ to, replace }: { to: string; replace?: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (replace) router.replace(to);
    else router.push(to);
  }, [router, to, replace]);
  return null;
}
