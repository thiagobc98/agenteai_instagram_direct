// Wrapper fino sobre fetch para as rotas /api/* da API.
//
// Usa credentials: "include" para enviar o cookie de sessão em toda
// chamada. Base URL vazia por padrão: em dev e no stack Docker, /api/*
// é servido na mesma origem do frontend via middleware.ts (proxy same-
// origin) ou, atrás do proxy em produção, diretamente pelo Caddy.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail || "Erro desconhecido");
  }

  return response.json() as Promise<T>;
}

export interface AdminUser {
  username: string;
}

export interface Metrics {
  total_today: number;
  failures_today: number;
  avg_processing_time_seconds: number | null;
  queue_size: number;
}

export interface Chat {
  external_id: string;
  agent_id: string;
  thread_id: string;
  last_message: string | null;
  last_message_at: string | null;
  message_count: number;
  created_at: string | null;
}

export interface ChatListResponse {
  chats: Chat[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChatMessage {
  id: number;
  agent_id: string;
  incoming_message: string | null;
  media_type: string | null;
  normalized_input: string | null;
  media_processing_status: string | null;
  response: string | null;
  status: string;
  created_at: string | null;
  processed_at: string | null;
  media_processing_error: string | null;
  error: string | null;
}

export interface ChatMessagesResponse {
  external_id: string;
  messages: ChatMessage[];
}

export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  all_day: boolean;
  external_id: string | null;
  patient_name: string | null;
}

export interface CalendarEventsResponse {
  enabled: boolean;
  calendar_id?: string;
  business_hour_start?: number;
  business_hour_end?: number;
  events: CalendarEvent[];
}

export const api = {
  login: (username: string, password: string) =>
    request<AdminUser>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  me: () => request<AdminUser>("/api/auth/me"),

  metrics: () => request<Metrics>("/api/metrics"),

  agents: () => request<{ agents: string[] }>("/api/agents"),

  chats: (limit = 20, offset = 0) =>
    request<ChatListResponse>(`/api/chats?limit=${limit}&offset=${offset}`),

  chatMessages: (externalId: string, limit = 50, offset = 0) =>
    request<ChatMessagesResponse>(
      `/api/chats/${encodeURIComponent(externalId)}?limit=${limit}&offset=${offset}`,
    ),

  calendarEvents: (start: Date, end: Date) =>
    request<CalendarEventsResponse>(
      `/api/calendar/events?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`,
    ),
};
