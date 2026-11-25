"use client";

// Um comentário de postagem com o rascunho de resposta da IA.
//
// Pendente: mostra as duas respostas (pública, embaixo do comentário, e
// privada, no Direct ou Messenger de quem comentou) em campos editáveis, com Aprovar e
// publicar / Refazer com IA / Ignorar. Respondido: mostra o que foi publicado.

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Post, type PostComment } from "../../lib/api";
import { CHANNELS, channelOf } from "../../lib/channels";
import { relativeTime } from "../../lib/format";
import Avatar from "../Avatar";
import { IconAlertCircle, IconCheck, IconClock, IconExternal, IconSparkle } from "../icons";
import styles from "./CommentCard.module.css";

const STATUS_LABEL: Record<string, { label: string; tone: string }> = {
  new: { label: "IA escrevendo", tone: "neutral" },
  drafting: { label: "IA escrevendo", tone: "neutral" },
  pending: { label: "Aguardando aprovação", tone: "warning" },
  sending: { label: "Publicando", tone: "neutral" },
  sent: { label: "Respondido", tone: "success" },
  ignored: { label: "Ignorado", tone: "muted" },
  failed: { label: "Falhou", tone: "danger" },
  archived: { label: "Antigo", tone: "muted" },
};

const PUBLIC_MAX = 2200;
const PRIVATE_MAX_BYTES = 1000;

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

export default function CommentCard({
  comment,
  post,
  postPermalink,
  onChange,
}: {
  comment: PostComment;
  // Só na fila de aprovação (todas as postagens): mostra de qual post é.
  post?: Post;
  // Na página de um post (sem `post`): link dele, para abrir o comentário
  postPermalink?: string | null;
  onChange: (updated: PostComment) => void;
}) {
  const [publicText, setPublicText] = useState(comment.draft_public ?? "");
  const [privateText, setPrivateText] = useState(comment.draft_private ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Rascunho novo chegou (polling ou "Refazer com IA"): atualiza os campos.
  useEffect(() => {
    setPublicText(comment.draft_public ?? "");
    setPrivateText(comment.draft_private ?? "");
  }, [comment.draft_public, comment.draft_private]);

  const status = STATUS_LABEL[comment.status] ?? { label: comment.status, tone: "neutral" };
  const drafting = comment.status === "new" || comment.status === "drafting";
  const editable = comment.status === "pending" || comment.status === "failed";
  const closed = comment.status === "ignored" || comment.status === "archived";
  const privateBytes = byteLength(privateText.trim());
  const privateAlreadySent = !!comment.reply_private_id;

  async function run(label: string, action: () => Promise<{ comment: PostComment }>) {
    setBusy(label);
    setError(null);
    try {
      const { comment: updated } = await action();
      onChange(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro desconhecido");
      // Recarrega o estado real (ex: status virou "failed").
      api
        .post(comment.media_id)
        .then((data) => {
          const fresh = data.comments.find((c) => c.comment_id === comment.comment_id);
          if (fresh) onChange(fresh);
        })
        .catch(() => {});
    } finally {
      setBusy(null);
    }
  }

  const channel = CHANNELS[channelOf(comment)];
  const author = channel.author(comment.from_username);
  const profileUrl = channel.profileUrl(comment.from_username);
  // Abre o comentário na rede: útil quando a Meta não informa o autor
  const commentUrl = channel.commentUrl(post?.permalink ?? postPermalink, comment.comment_id);

  return (
    <article className={`card ${styles.card} ${closed ? styles.closed : ""}`}>
      {post && (
        <Link
          className={styles.postRef}
          href={`${channel.basePath}/${encodeURIComponent(post.media_id)}`}
        >
          {(post.thumbnail_url || post.media_url) && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={post.thumbnail_url || post.media_url || ""}
              alt=""
              className={styles.postThumb}
              referrerPolicy="no-referrer"
            />
          )}
          <span className={styles.postCaption}>{post.caption || "Postagem sem legenda"}</span>
        </Link>
      )}

      <header className={styles.header}>
        <Avatar seed={comment.from_id || comment.comment_id} size={34} />
        <div className={styles.who}>
          <p className={styles.author}>
            {profileUrl ? (
              <a href={profileUrl} target="_blank" rel="noopener noreferrer">
                {author}
              </a>
            ) : (
              author
            )}
            {comment.parent_id && <span className={styles.replyTag}>resposta</span>}
          </p>
          <p className={styles.time}>
            {relativeTime(comment.commented_at)}
            {commentUrl && (
              <>
                {" · "}
                <a
                  href={commentUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.viewLink}
                >
                  Ver no {channel.name} <IconExternal size={11} />
                </a>
              </>
            )}
          </p>
        </div>
        <span className={`${styles.badge} ${styles[status.tone]}`}>
          {status.tone === "success" && <IconCheck size={12} />}
          {status.tone === "warning" && <IconClock size={12} />}
          {status.tone === "danger" && <IconAlertCircle size={12} />}
          {status.label}
        </span>
      </header>

      <p className={styles.text}>{comment.text || <em className="muted">(sem texto)</em>}</p>

      {drafting && (
        <p className={styles.drafting}>
          <IconSparkle size={14} /> A IA está escrevendo o rascunho...
        </p>
      )}

      {comment.error && comment.status === "failed" && (
        <p className={styles.errorBox}>
          <IconAlertCircle size={14} /> {comment.error}
        </p>
      )}

      {editable && (
        <div className={styles.drafts}>
          {comment.ai_suggests_ignore && (
            <p className={styles.suggestIgnore}>
              <IconSparkle size={14} /> A IA sugere ignorar
              {comment.ai_reason ? `: ${comment.ai_reason}` : "."}
            </p>
          )}

          <label className={styles.field}>
            <span className={styles.fieldLabel}>
              Resposta pública <small>embaixo do comentário, todos veem</small>
            </span>
            <textarea
              value={publicText}
              onChange={(e) => setPublicText(e.target.value)}
              rows={2}
              maxLength={PUBLIC_MAX}
              disabled={!!busy || !!comment.reply_public_id}
            />
            {comment.reply_public_id && (
              <span className={styles.hint}>Já publicada. Falta só a privada.</span>
            )}
          </label>

          <label className={styles.field}>
            <span className={styles.fieldLabel}>
              Mensagem privada{" "}
              <small>no {channel.dm} de quem comentou, deixe vazio para não enviar</small>
            </span>
            <textarea
              value={privateText}
              onChange={(e) => setPrivateText(e.target.value)}
              rows={3}
              disabled={!!busy || privateAlreadySent}
            />
            <span
              className={`${styles.hint} ${privateBytes > PRIVATE_MAX_BYTES ? styles.over : ""}`}
            >
              {privateBytes}/{PRIVATE_MAX_BYTES} bytes
            </span>
          </label>

          {error && <p className="error-text">{error}</p>}

          <div className={styles.actions}>
            {comment.ai_suggests_ignore && !comment.reply_public_id && (
              <button
                onClick={() =>
                  run("ignore", () => api.commentAction(comment.comment_id, "ignore"))
                }
                disabled={!!busy}
              >
                {busy === "ignore" ? "Ignorando..." : "Ignorar (sugestão da IA)"}
              </button>
            )}
            <button
              className={comment.ai_suggests_ignore ? styles.ghost : undefined}
              onClick={() =>
                run("approve", () =>
                  api.approveComment(comment.comment_id, publicText, privateText),
                )
              }
              disabled={
                !!busy || !publicText.trim() || privateBytes > PRIVATE_MAX_BYTES
              }
            >
              {busy === "approve"
                ? "Publicando..."
                : privateText.trim()
                  ? "Aprovar e enviar as duas"
                  : "Aprovar resposta pública"}
            </button>
            {!comment.reply_public_id && (
              <button
                className={styles.secondary}
                onClick={() =>
                  run("redraft", () => api.commentAction(comment.comment_id, "redraft"))
                }
                disabled={!!busy}
              >
                <IconSparkle size={14} /> {busy === "redraft" ? "Pedindo..." : "Refazer com IA"}
              </button>
            )}
            {!comment.reply_public_id && !comment.ai_suggests_ignore && (
              <button
                className={styles.ghost}
                onClick={() =>
                  run("ignore", () => api.commentAction(comment.comment_id, "ignore"))
                }
                disabled={!!busy}
              >
                Ignorar
              </button>
            )}
          </div>
        </div>
      )}

      {comment.status === "sent" && (
        <div className={styles.replies}>
          {comment.reply_public_text && (
            <div className={styles.reply}>
              <span className={styles.replyLabel}>Resposta pública</span>
              <p>{comment.reply_public_text}</p>
            </div>
          )}
          {comment.reply_private_text && (
            <div className={styles.reply}>
              <span className={styles.replyLabel}>Mensagem no {channel.dm}</span>
              <p>{comment.reply_private_text}</p>
            </div>
          )}
          {comment.private_error && (
            <p className={styles.errorBox}>
              <IconAlertCircle size={14} /> Mensagem privada não enviada: {comment.private_error}
            </p>
          )}
        </div>
      )}

      {closed && (
        <div className={styles.actions}>
          <button
            className={styles.ghost}
            onClick={() => run("reopen", () => api.commentAction(comment.comment_id, "reopen"))}
            disabled={!!busy}
          >
            {busy === "reopen" ? "Reabrindo..." : "Responder mesmo assim"}
          </button>
          {error && <p className="error-text">{error}</p>}
        </div>
      )}
    </article>
  );
}
