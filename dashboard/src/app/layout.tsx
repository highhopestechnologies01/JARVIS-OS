import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JARVIS OS",
  description: "Executive AI Operating System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-jarvis-bg text-jarvis-text antialiased min-h-screen font-sans">
        {children}
      </body>
    </html>
  );
}
