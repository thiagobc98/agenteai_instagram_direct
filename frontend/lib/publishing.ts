// Rótulos e utilitários compartilhados pelas telas de publicação.

import type { PublicationKind, PublicationStatus, VideoMeta } from "./api";

export const KIND_LABEL: Record<PublicationKind, string> = {
  feed: "Feed",
  story: "Story",
  reels: "Reels",
};

export const KIND_HINT: Record<PublicationKind, string> = {
  feed: "Foto (4:5 a 1,91:1) ou carrossel de até 10 fotos/vídeos",
  story: "1 foto ou vídeo vertical (9:16), até 60s. Some em 24h",
  reels: "1 vídeo vertical (9:16), de 3s a 15min",
};

export const STATUS_LABEL: Record<
  PublicationStatus,
  { label: string; tone: "success" | "warning" | "danger" | "neutral" }
> = {
  draft: { label: "Rascunho", tone: "neutral" },
  scheduled: { label: "Agendada", tone: "warning" },
  processing: { label: "Enviando à Meta", tone: "warning" },
  publishing: { label: "Publicando", tone: "warning" },
  published: { label: "Publicada", tone: "success" },
  failed: { label: "Falhou", tone: "danger" },
  canceled: { label: "Descartada", tone: "neutral" },
};

export const IN_FLIGHT: PublicationStatus[] = ["scheduled", "processing", "publishing"];

export const MAX_CAPTION = 2200;
export const MAX_HASHTAGS = 30;
export const MAX_MENTIONS = 20;

export function countHashtags(text: string): number {
  return (text.match(/(^|[^\w])#[\p{L}\p{N}_]+/gu) || []).length;
}

export function countMentions(text: string): number {
  return (text.match(/(^|[^\w@])@[\p{L}\p{N}_.]+/gu) || []).length;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Valor para <input type="datetime-local"> no fuso do navegador. */
export function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/**
 * Lê duração e dimensões do vídeo no navegador (o servidor não decodifica
 * vídeo). Falha silenciosa: a Meta valida de novo ao processar.
 */
export function readVideoMeta(file: File): Promise<VideoMeta> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    const done = (meta: VideoMeta) => {
      URL.revokeObjectURL(url);
      resolve(meta);
    };
    video.onloadedmetadata = () =>
      done({
        duration_seconds: Number.isFinite(video.duration) ? video.duration : undefined,
        width: video.videoWidth || undefined,
        height: video.videoHeight || undefined,
      });
    video.onerror = () => done({});
    setTimeout(() => done({}), 8000);
    video.src = url;
  });
}
