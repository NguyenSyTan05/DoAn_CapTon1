import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "i.pravatar.cc",
      },
    ],
  },
  // Nguồn được phép mở dev server. Muốn mở từ máy khác trong LAN, thêm IP của máy chạy dev vào đây
  allowedDevOrigins: ["localhost"],
  // Có nhiều package-lock.json ở thư mục cha -> chỉ rõ thư mục gốc của frontend
  turbopack: { root: projectRoot },
};

export default nextConfig;
