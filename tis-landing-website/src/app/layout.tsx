import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TIS Platform | Smarter Teacher Planning for Modern Schools",
  description:
    "A secure SaaS platform for schools to manage teacher information, workloads, subjects, academic operations, and staffing needs.",
  metadataBase: new URL("https://tisplatform.com")
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
