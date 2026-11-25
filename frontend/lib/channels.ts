// O que muda entre as telas de comentários do Instagram e do Facebook.
// Centralizado aqui para os componentes não espalharem `if (channel === ...)`.

import type { Channel } from "./api";

export interface ChannelConfig {
  /** Nome da rede para textos ("Ver no Instagram") */
  name: string;
  /** Onde a mensagem privada chega para quem comentou */
  dm: string;
  /** Tela da fila de comentários (as postagens ficam em `${basePath}/<id>`) */
  basePath: string;
  /** Como mostrar o autor: @ no Instagram, nome no Facebook */
  author: (fromUsername: string | null) => string;
  /** Link do perfil do autor, quando a rede permite montar um */
  profileUrl: (fromUsername: string | null) => string | null;
  /** Link que abre o próprio comentário na rede (null se não der para montar) */
  commentUrl: (postPermalink: string | null | undefined, commentId: string) => string | null;
}

/** Só aceita links https de um dos domínios esperados (defesa contra
 * `javascript:` ou domínios estranhos vindos de dados externos). */
function safeUrl(raw: string | null | undefined, hosts: string[]): URL | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    const host = url.hostname.replace(/^(www|m|web)\./, "");
    return url.protocol === "https:" && hosts.includes(host) ? url : null;
  } catch {
    return null;
  }
}

/** Comentário do Facebook: link do post + ?comment_id=<parte do comentário>.
 * O ID vem como "<post>_<comentário>"; o Facebook abre o post já rolado até ele. */
function facebookCommentUrl(permalink: string | null | undefined, commentId: string) {
  const url = safeUrl(permalink, ["facebook.com"]);
  if (!url) return null;
  const local = commentId.includes("_") ? commentId.split("_").pop()! : commentId;
  if (!/^\d+$/.test(local)) return url.toString();
  url.searchParams.set("comment_id", local);
  return url.toString();
}

export const CHANNELS: Record<Channel, ChannelConfig> = {
  instagram: {
    name: "Instagram",
    dm: "Direct",
    basePath: "/posts",
    author: (u) => (u ? `@${u}` : "Usuário do Instagram"),
    profileUrl: (u) => (u ? `https://instagram.com/${encodeURIComponent(u)}` : null),
    // A API do Instagram não dá link para um comentário específico
    commentUrl: () => null,
  },
  facebook: {
    name: "Facebook",
    dm: "Messenger",
    basePath: "/facebook",
    author: (name) => name || "Pessoa no Facebook",
    // O Facebook só entrega um ID por Página (PSID): não dá link de perfil
    profileUrl: () => null,
    commentUrl: facebookCommentUrl,
  },
};

export function channelOf(item: { channel?: Channel } | null | undefined): Channel {
  return item?.channel ?? "instagram";
}
