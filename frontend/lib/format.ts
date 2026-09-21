// Utilitários de formatação para exibição de contatos, datas e mensagens
// no Admin Panel. Todos os valores de entrada vêm de dados reais da API
// (telefone E.164, timestamps ISO) — nada aqui inventa informação.

export function formatPhone(raw: string): string {
  const digits = raw.replace(/^whatsapp:/, "").replace(/\D/g, "");
  if (!digits) return raw;

  // Brasil: 55 + DDD (2) + número (8 ou 9 dígitos)
  if (digits.startsWith("55") && (digits.length === 12 || digits.length === 13)) {
    const ddd = digits.slice(2, 4);
    const rest = digits.slice(4);
    const mid = rest.length === 9 ? rest.slice(0, 5) : rest.slice(0, 4);
    const end = rest.length === 9 ? rest.slice(5) : rest.slice(4);
    return `+55 (${ddd}) ${mid}-${end}`;
  }

  return `+${digits}`;
}

const AGENT_DISPLAY_NAMES: Record<string, string> = {
  secretaria: "Secretária",
};

export function formatAgentName(agentId: string): string {
  return AGENT_DISPLAY_NAMES[agentId] ?? agentId;
}

const AVATAR_HUES = [142, 160, 174, 190, 204, 260, 280];

export function avatarHue(raw: string): number {
  let hash = 0;
  for (let i = 0; i < raw.length; i++) {
    hash = (hash * 31 + raw.charCodeAt(i)) >>> 0;
  }
  return AVATAR_HUES[hash % AVATAR_HUES.length];
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);

  if (diffMin < 1) return "agora";
  if (diffMin < 60) return `há ${diffMin} min`;

  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return "ontem";
  }

  const sameYear = date.getFullYear() === now.getFullYear();
  return date.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: sameYear ? undefined : "numeric",
  });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("pt-BR");
}

export function formatDateSeparator(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  const now = new Date();

  if (date.toDateString() === now.toDateString()) return "Hoje";

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Ontem";

  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "long", year: "numeric" });
}

export function formatTime(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}
