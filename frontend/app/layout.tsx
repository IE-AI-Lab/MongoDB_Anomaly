import type { Metadata } from "next";

import "./globals.css";
import { TopBar } from "@/components/TopBar";
import { ChatWidget } from "@/components/ChatWidget";

export const metadata: Metadata = {
  title: "Anomaly Platform",
  description: "CNC/industrial anomaly-detection operator console",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <TopBar />
        <main className="mx-auto max-w-[1600px] px-4 py-5">{children}</main>
        <ChatWidget />
      </body>
    </html>
  );
}
