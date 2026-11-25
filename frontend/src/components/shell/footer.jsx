"use client";

import { useState } from "react";
import Image from "next/image";
import { Link } from "@/lib/router-compat";
import {
  Check,
  Copy,
  Mail,
  MapPin,
} from "lucide-react";
import "./footer.css";

const contactEmail = "classbridge38@gmail.com";

export default function Footer({ language = "vi" }) {
  const isVi = language === "vi";
  const [copyStatus, setCopyStatus] = useState("");

  const handleCopyEmail = async () => {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API is unavailable");
      }
      await navigator.clipboard.writeText(contactEmail);
      setCopyStatus(isVi ? "Đã sao chép email" : "Email copied");
    } catch (error) {
      console.error("Could not copy the contact email:", error);
      setCopyStatus(
        isVi ? "Không thể sao chép email" : "Could not copy email",
      );
    }
  };

  return (
    <footer className="site-footer">
      <div className="site-footer-grid">
        <section className="site-footer-section site-footer-brand-card">
          <div className="site-footer-brand-heading">
            <span className="site-footer-logo" aria-hidden="true">
              <Image
                src="/classbridge-logo-transparent.png"
                alt=""
                width={38}
                height={38}
              />
            </span>
            <div className="site-footer-brand-copy">
              <h2>
                ClassBridge <span>– AI</span>
              </h2>
              <p>
                {isVi
                  ? "Trợ giảng AI lớp học song ngữ EMI · DTU"
                  : "AI teaching assistant for bilingual EMI classes · DTU"}
              </p>
            </div>
          </div>
          
        </section>

        <nav
          className="site-footer-section site-footer-navigation"
          aria-label={isVi ? "Điều hướng và hỗ trợ" : "Navigation and support"}
        >
          <h2>{isVi ? "ĐIỀU HƯỚNG & HỖ TRỢ" : "NAVIGATION & SUPPORT"}</h2>
          <ul>
            <li>
              <Link to="/">{isVi ? "Trang chủ" : "Home"}</Link>
            </li>
            <li>
              <Link to="/#tinh-nang">{isVi ? "Giới thiệu" : "About"}</Link>
            </li>
            <li>
              <span>{isVi ? "Chính sách Bảo mật" : "Privacy Policy"}</span>
            </li>
            <li>
              <span>{isVi ? "Điều khoản Dịch vụ" : "Terms of Service"}</span>
            </li>
            <li>
              <a href={`mailto:${contactEmail}`}>
                {isVi ? "Trung tâm trợ giúp" : "Help center"}
              </a>
            </li>
          </ul>
        </nav>

        <section className="site-footer-section site-footer-contact">
          <h2>{isVi ? "LIÊN HỆ" : "CONTACT"}</h2>
          <p className="site-footer-location">
            <MapPin size={15} aria-hidden="true" />
            <span>{isVi ? "Trường Chinh, Đà Nẵng, Việt Nam" : "Da Nang, Vietnam"}</span>
          </p>
          <div className="site-footer-email">
            <Mail size={15} aria-hidden="true" />
            <a href={`mailto:${contactEmail}`}>{contactEmail}</a>
            <button
              type="button"
              onClick={handleCopyEmail}
              aria-label={isVi ? "Sao chép email" : "Copy email"}
              title={copyStatus || (isVi ? "Sao chép email" : "Copy email")}
            >
              {copyStatus.startsWith(isVi ? "Đã" : "Email copied") ? (
                <Check size={15} aria-hidden="true" />
              ) : (
                <Copy size={15} aria-hidden="true" />
              )}
            </button>
          </div>
          {copyStatus && (
            <span className="site-footer-copy-status" role="status">
              {copyStatus}
            </span>
          )}
        </section>
      </div>
      <p className="site-footer-copyright">
        © {new Date().getFullYear()} ClassBridge – AI
      </p>
    </footer>
  );
}
