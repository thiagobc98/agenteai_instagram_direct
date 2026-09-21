import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Central Berberich",
  description: "Central de atendimento da loja Patricia Berberich no Instagram Direct",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
