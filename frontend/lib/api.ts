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
  username: string | null;
  name: string | null;
  profile_pic_url: string | null;
  whatsapp: string | null;
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
  username: string | null;
  name: string | null;
  profile_pic_url: string | null;
  whatsapp: string | null;
  messages: ChatMessage[];
  /** Mensagens privadas enviadas pela tela de comentários (fora da fila do Direct). */
  comment_replies?: CommentDmReply[];
}

export interface CommentDmReply {
  comment_id: string;
  comment_text: string;
  commented_at: string | null;
  private_text: string;
  sent_at: string | null;
  approved_by: string | null;
  post_permalink: string | null;
  post_caption: string | null;
}

export interface DailyPoint {
  date: string;
  messages: number;
  contacts: number;
  new_leads: number;
  handoffs: number;
  handoff_contacts: number;
}

export interface HandoffContact {
  external_id: string;
  username: string | null;
  name: string | null;
  profile_pic_url: string | null;
  whatsapp: string | null;
  last_message: string | null;
  at: string | null;
}

export interface Dashboard {
  period_days: number;
  timezone: string;
  generated_at: string;
  handoff_enabled: boolean;
  today: DailyPoint;
  yesterday: DailyPoint | null;
  period: {
    messages: number;
    contacts: number;
    new_leads: number;
    returning_contacts: number;
    handoff_messages: number;
    handoff_contacts: number;
    handoff_contact_rate: number;
    ai_only_rate: number;
    answered_messages: number;
    failures: number;
    total_contacts: number;
  };
  daily: DailyPoint[];
  by_hour: number[];
  by_weekday: number[];
  media: { text: number; image: number; audio: number };
  topics: { key: string; label: string; count: number }[];
  handoff_queue: HandoffContact[];
}

export interface Post {
  media_id: string;
  caption: string | null;
  media_type: string | null;
  media_url: string | null;
  thumbnail_url: string | null;
  permalink: string | null;
  posted_at: string | null;
  comments_count: number | null;
  synced_at: string | null;
  tracked_comments?: number;
  pending_comments?: number;
  last_comment_at?: string | null;
}

export type CommentStatus =
  | "new"
  | "drafting"
  | "pending"
  | "sending"
  | "sent"
  | "ignored"
  | "failed"
  | "archived";

export interface PostComment {
  comment_id: string;
  media_id: string;
  parent_id: string | null;
  from_id: string | null;
  from_username: string | null;
  text: string;
  commented_at: string | null;
  status: CommentStatus;
  draft_public: string | null;
  draft_private: string | null;
  ai_suggests_ignore: boolean;
  ai_reason: string | null;
  reply_public_id: string | null;
  reply_public_text: string | null;
  reply_private_id: string | null;
  reply_private_text: string | null;
  private_error: string | null;
  error: string | null;
  sent_at: string | null;
  approved_by: string | null;
}

export interface PostsResponse {
  posts: Post[];
  counts: Record<string, number>;
  pending_total: number;
}

export interface PostDetailResponse {
  post: Post;
  comments: PostComment[];
}

export interface CommentQueueResponse {
  comments: PostComment[];
  posts: Record<string, Post>;
}

export interface SyncResponse {
  posts: number;
  new_comments: number;
  failed_posts: number;
}

type CommentAction = "ignore" | "reopen" | "redraft";

export type PublicationKind = "feed" | "story" | "reels";

export type PublicationStatus =
  | "draft"
  | "scheduled"
  | "processing"
  | "publishing"
  | "published"
  | "failed"
  | "canceled";

export interface PublicationMedia {
  id: number;
  position: number;
  token: string;
  media_kind: "image" | "video";
  content_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  original_name: string | null;
  ai_description: string | null;
}

export interface PublicationValidation {
  errors: string[];
  warnings: string[];
  public_url_problem: string | null;
}

export interface Publication {
  id: number;
  kind: PublicationKind;
  status: PublicationStatus;
  brief: string;
  caption: string;
  ai_caption: string | null;
  share_to_feed: boolean;
  publish_at: string | null;
  ig_media_id: string | null;
  permalink: string | null;
  error: string | null;
  attempts: number;
  created_by: string | null;
  approved_by: string | null;
  published_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  origin: "manual" | "agent";
  planned_for: string | null;
  rationale: string | null;
  media?: PublicationMedia[];
  validation?: PublicationValidation;
  // Só na listagem
  cover_token?: string | null;
  cover_kind?: "image" | "video" | null;
  media_count?: number;
}

export type MarketingAction =
  | { type: "draft"; publication_id: number; kind: PublicationKind; planned_for: string; title: string }
  | { type: "tools"; names: string[] }
  | { type: "error" };

export interface MarketingMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  actions: MarketingAction[];
  created_by: string | null;
  created_at: string | null;
}

export interface MarketingThread {
  id: number;
  title: string;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PublishingQuota {
  quota_usage: number | null;
  quota_total: number | null;
  public_url_problem: string | null;
}

export interface VideoMeta {
  duration_seconds?: number;
  width?: number;
  height?: number;
}

/** URL da mídia servida pela API (mesma que a Meta baixa). */
export function mediaUrl(token: string): string {
  return `${API_BASE_URL}/media/${encodeURIComponent(token)}`;
}

/**
 * Upload com progresso. fetch() não informa progresso de envio, e um Reels
 * pode ter centenas de MB: por isso XMLHttpRequest.
 */
export function uploadPublicationMedia(
  pubId: number,
  file: File,
  meta: VideoMeta,
  onProgress: (fraction: number) => void,
): Promise<{ publication: Publication }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    if (meta.duration_seconds != null) form.append("duration_seconds", String(meta.duration_seconds));
    if (meta.width != null) form.append("width", String(meta.width));
    if (meta.height != null) form.append("height", String(meta.height));

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/publications/${pubId}/media`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: { detail?: string; publication?: Publication } = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* resposta não-JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300 && body.publication) {
        resolve({ publication: body.publication });
      } else {
        reject(new ApiError(xhr.status, body.detail || `Falha no upload (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Falha de rede no upload"));
    xhr.send(form);
  });
}

export interface WhatsappConnection {
  configured: boolean;
  online: boolean;
  instance_exists: boolean;
  connected: boolean;
  logged_in: boolean;
  number: string | null;
  qr_code: string | null;
  can_create_instance: boolean;
  error: string | null;
}

export interface NotifySettings {
  enabled: boolean;
  recipients: string[];
  updated_by: string | null;
  updated_at: string | null;
}

export interface AttendantNotification {
  id: number;
  external_id: string;
  username: string | null;
  preview: string;
  status: "pending" | "sending" | "sent" | "failed" | "skipped";
  attempts: number;
  error: string | null;
  created_at: string | null;
  sent_at: string | null;
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

  dashboard: (days = 14) => request<Dashboard>(`/api/dashboard?days=${days}`),

  agents: () => request<{ agents: string[] }>("/api/agents"),

  chats: (limit = 20, offset = 0) =>
    request<ChatListResponse>(`/api/chats?limit=${limit}&offset=${offset}`),

  chatMessages: (externalId: string, limit = 50, offset = 0) =>
    request<ChatMessagesResponse>(
      `/api/chats/${encodeURIComponent(externalId)}?limit=${limit}&offset=${offset}`,
    ),

  posts: () => request<PostsResponse>("/api/posts"),

  syncPosts: () => request<SyncResponse>("/api/posts/sync", { method: "POST" }),

  post: (mediaId: string) =>
    request<PostDetailResponse>(`/api/posts/${encodeURIComponent(mediaId)}`),

  commentQueue: (order: "newest" | "oldest" = "newest") =>
    request<CommentQueueResponse>(`/api/comments?status=pending&order=${order}`),

  approveComment: (commentId: string, publicText: string, privateText: string) =>
    request<{ comment: PostComment }>(
      `/api/comments/${encodeURIComponent(commentId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ public_text: publicText, private_text: privateText }),
      },
    ),

  commentAction: (commentId: string, action: CommentAction) =>
    request<{ comment: PostComment }>(
      `/api/comments/${encodeURIComponent(commentId)}/${action}`,
      { method: "POST" },
    ),

  publications: () => request<{ publications: Publication[] }>("/api/publications"),

  publishingQuota: () => request<PublishingQuota>("/api/publications/quota"),

  createPublication: (kind: PublicationKind) =>
    request<{ publication: Publication }>("/api/publications", {
      method: "POST",
      body: JSON.stringify({ kind }),
    }),

  publication: (id: number) => request<{ publication: Publication }>(`/api/publications/${id}`),

  updatePublication: (
    id: number,
    fields: Partial<Pick<Publication, "kind" | "brief" | "caption" | "share_to_feed">>,
  ) =>
    request<{ publication: Publication }>(`/api/publications/${id}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    }),

  removePublicationMedia: (id: number, mediaId: number) =>
    request<{ publication: Publication }>(`/api/publications/${id}/media/${mediaId}`, {
      method: "DELETE",
    }),

  reorderPublicationMedia: (id: number, mediaIds: number[]) =>
    request<{ publication: Publication }>(`/api/publications/${id}/media/order`, {
      method: "PUT",
      body: JSON.stringify({ media_ids: mediaIds }),
    }),

  generateCaption: (id: number) =>
    request<{ publication: Publication; notes: string | null }>(
      `/api/publications/${id}/caption`,
      { method: "POST" },
    ),

  schedulePublication: (id: number, publishAt: string | null) =>
    request<{ publication: Publication }>(`/api/publications/${id}/schedule`, {
      method: "POST",
      body: JSON.stringify({ publish_at: publishAt }),
    }),

  unschedulePublication: (id: number) =>
    request<{ publication: Publication }>(`/api/publications/${id}/unschedule`, {
      method: "POST",
    }),

  cancelPublication: (id: number) =>
    request<{ ok: boolean }>(`/api/publications/${id}`, { method: "DELETE" }),

  whatsappStatus: () =>
    request<{ connection: WhatsappConnection; settings: NotifySettings }>(
      "/api/whatsapp/status",
    ),

  whatsappConnect: () =>
    request<{ connection: WhatsappConnection }>("/api/whatsapp/connect", { method: "POST" }),

  whatsappDisconnect: () =>
    request<{ connection: WhatsappConnection }>("/api/whatsapp/disconnect", {
      method: "POST",
    }),

  saveNotifySettings: (enabled: boolean, recipients: string[]) =>
    request<{ settings: NotifySettings }>("/api/whatsapp/settings", {
      method: "PUT",
      body: JSON.stringify({ enabled, recipients }),
    }),

  sendNotifyTest: () =>
    request<{ results: { phone: string; ok: boolean; error: string | null }[] }>(
      "/api/whatsapp/test",
      { method: "POST" },
    ),

  attendantNotifications: () =>
    request<{ notifications: AttendantNotification[] }>("/api/whatsapp/notifications"),

  marketingThreads: () => request<{ threads: MarketingThread[] }>("/api/marketing/threads"),

  createMarketingThread: () =>
    request<{ thread: MarketingThread }>("/api/marketing/threads", {
      method: "POST",
      body: JSON.stringify({}),
    }),

  marketingThread: (id: number) =>
    request<{ thread: MarketingThread; messages: MarketingMessage[]; busy: boolean }>(
      `/api/marketing/threads/${id}`,
    ),

  deleteMarketingThread: (id: number) =>
    request<{ ok: boolean }>(`/api/marketing/threads/${id}`, { method: "DELETE" }),

  askMarketing: (id: number, content: string) =>
    request<{ messages: MarketingMessage[] }>(`/api/marketing/threads/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
};
