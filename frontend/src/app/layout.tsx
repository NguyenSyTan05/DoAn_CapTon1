import type { Metadata, Viewport } from "next";
import "./globals.css";
import ActivityTracker from "../components/shell/ActivityTracker";

export const metadata: Metadata = {
  title: "ClassBridge - AI Classroom",
  description: "Nền tảng phòng học ảo AI hỗ trợ dịch thuật song ngữ theo thời gian thực",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "ClassBridge - AI Classroom",
  }
};
export const viewport: Viewport = {
  themeColor: "#2563eb",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};


export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body className="bg-[#0b1120] text-slate-200 antialiased">
        <ActivityTracker />
        {children}
      </body>
    </html>
  );
}