import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TIS Platform | Connected Academic Operations for Schools",
  description:
    "A developing SaaS academic operations platform connecting teacher workforce planning, observations, calendars, branches, dashboards, and future AI-powered intelligence.",
  metadataBase: new URL("https://tisplatform.com"),
  icons: {
    icon: "/branding/tis/logos/tis-wordmark-dark-blue.png"
  }
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
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
