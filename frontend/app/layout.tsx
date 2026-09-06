import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "소싱 대시보드",
  description: "내부 소싱 상품 관리 대시보드",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
