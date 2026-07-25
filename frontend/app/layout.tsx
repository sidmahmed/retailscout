import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RetailScout",
  description:
    "Compare locations for a café, retail shop, food truck or pop-up in the City of Melbourne — with evidence and explicit data confidence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
