import type { Metadata } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";
import FloodGuardAssistant from "../components/FloodGuardAssistant";

export const metadata: Metadata = {
  title: "FloodGuard | Route preview",
  description: "Real-Time Flood Intelligence & Safe Routing",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        {children}
        <FloodGuardAssistant />
      </body>
    </html>
  );
}
