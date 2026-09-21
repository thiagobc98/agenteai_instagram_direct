import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Instagram Direct — Admin",
  description: "Painel administrativo do atendimento no Instagram Direct",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
