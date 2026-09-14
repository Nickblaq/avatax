import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MediaForge",
  description: "Download video, audio & images from 30+ platforms",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#f5f5f7] text-[#1a1a2e] antialiased">
        {children}
      </body>
    </html>
  );
}
