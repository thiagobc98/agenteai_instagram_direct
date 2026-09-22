// Utilitários de formatação para exibição de contatos, datas e mensagens
// no Admin Panel. Todos os valores de entrada vêm de dados reais da API
// (ID do contato no Instagram, timestamps ISO) — nada aqui inventa informação.

// O contato é identificado pelo IGSID do Instagram (ID numérico, exibido como
// está). Conversas antigas do WhatsApp têm o telefone E.164 ("+55...") como
// identificador — para elas mantemos a formatação de telefone.
export function formatContactId(raw: string): string {
  const isLegacyPhone = raw.startsWith("+") || raw.startsWith("whatsapp:");
  if (!isLegacyPhone) return raw;

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
  secretaria: "Atendente virtual",
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

// ---------- Contatos (perfil do Instagram) ----------

interface ContactLike {
  external_id: string;
  username?: string | null;
  name?: string | null;
}

// Nome principal do contato: @usuario quando o perfil é conhecido; senão o
// nome de exibição; por último o ID numérico.
export function contactLabel(contact: ContactLike): string {
  if (contact.username) return `@${contact.username}`;
  if (contact.name) return contact.name;
  return formatContactId(contact.external_id);
}

// ---------- Números e datas do dashboard ----------

export function formatNumber(value: number): string {
  return value.toLocaleString("pt-BR");
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const min = Math.floor(seconds / 60);
  const sec = Math.round(seconds % 60);
  return sec ? `${min}min ${sec}s` : `${min}min`;
}

export const WEEKDAYS_SHORT = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
export const WEEKDAYS_LONG = [
  "domingo",
  "segunda-feira",
  "terça-feira",
  "quarta-feira",
  "quinta-feira",
  "sexta-feira",
  "sábado",
];

// "2026-09-21" -> "21/09" (sem passar por Date: evita erro de fuso).
export function formatShortDate(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  return `${day}/${month}`;
}

// ---------- WhatsApp da cliente (coletado pelo agente antes do encaminhamento) ----------

// Vem do backend normalizado: só dígitos, com o 55 do Brasil na frente
// (ex: "5531999998888") — pronto para um link "https://wa.me/<numero>".
export function whatsappLink(whatsapp: string | null): string | null {
  return whatsapp ? `https://wa.me/${whatsapp}` : null;
}

// Reaproveita a formatação de telefone de formatContactId (mesmo formato
// "+55 (DDD) NNNNN-NNNN" que já usamos para o WhatsApp herdado do WhatsApp).
export function formatWhatsapp(whatsapp: string | null): string | null {
  return whatsapp ? formatContactId(`+${whatsapp}`) : null;
}
