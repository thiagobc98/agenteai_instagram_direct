"use client";

// Fila de comentários para aprovar + grade de postagens de UM canal.
// Usado pelas telas Postagens (Instagram) e Facebook: o que muda entre elas
// vem de `lib/channels.ts` e das props.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  api,
  type Channel,
  type CommentQueueResponse,
  type PostsResponse,
  type SyncResponse,
} from "../../lib/api";
import { CHANNELS } from "../../lib/channels";
import { relativeTime } from "../../lib/format";
import CommentCard from "./CommentCard";
import EmptyState from "../EmptyState";
import { IconGrid, IconInbox, IconPhoto, IconRepeat } from "../icons";
import styles from "./CommentsWorkspace.module.css";

type Tab = "queue" | "posts";
type Order = "newest" | "oldest";

// Enquanto a IA escreve rascunhos, recarrega a fila para mostrá-los.
const POLL_MS = 5000;

export default function CommentsWorkspace({
  channel,
  title,
  subtitle,
  sync,
  banner,
  disabled = false,
}: {
  channel: Channel;
  title: string;
  subtitle: string;
  /** Sincroniza postagens e comentários do canal com a Graph API */
  sync: () => Promise<SyncResponse>;
  /** Aviso acima do conteúdo (ex: situação da conexão com a Página) */
  banner?: ReactNode;
  /** Canal ainda não configurado: esconde ações que chamariam a Meta */
  disabled?: boolean;
}) {
  const config = CHANNELS[channel];
  // Ordem da fila escolhida pela equipe, salva por canal neste navegador
  const orderKey = `comments-queue-order:${channel}`;

  const [tab, setTab] = useState<Tab>("queue");
  const [order, setOrder] = useState<Order>("newest");
  const [orderReady, setOrderReady] = useState(false);
  const [posts, setPosts] = useState<PostsResponse | null>(null);
  const [queue, setQueue] = useState<CommentQueueResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  useEffect(() => {
    // Chave antiga (sem canal) da tela do Instagram continua valendo
    const saved =
      window.localStorage.getItem(orderKey) ??
      (channel === "instagram" ? window.localStorage.getItem("comments-queue-order") : null);
    if (saved === "newest" || saved === "oldest") setOrder(saved);
    setOrderReady(true);
  }, [orderKey, channel]);

  function changeOrder(next: Order) {
    setOrder(next);
    window.localStorage.setItem(orderKey, next);
  }

  const load = useCallback(async () => {
    try {
      const [p, q] = await Promise.all([api.posts(channel), api.commentQueue(order, channel)]);
      setPosts(p);
      setQueue(q);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar");
    }
  }, [order, channel]);

  useEffect(() => {
    // Espera ler a ordem salva para não buscar a fila duas vezes
    if (orderReady) load();
  }, [load, orderReady]);

  const drafting = queue?.comments.some((c) => c.status === "new" || c.status === "drafting");
  useEffect(() => {
    if (!drafting) return;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [drafting, load]);

  async function runSync() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const r = await sync();
      setSyncMsg(
        `${r.posts} postagens sincronizadas, ${r.new_comments} comentários novos` +
          (r.failed_posts ? ` (${r.failed_posts} postagens com erro)` : ""),
      );
      await load();
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Erro ao sincronizar");
    } finally {
      setSyncing(false);
    }
  }

  const pendingTotal = posts?.pending_total ?? 0;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>{title}</h1>
          <p className={styles.sub}>{subtitle}</p>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.tabs} role="group" aria-label="Visão">
            <button
              className={`${styles.tab} ${tab === "queue" ? styles.tabActive : ""}`}
              onClick={() => setTab("queue")}
            >
              Para aprovar
              {pendingTotal > 0 && <span className={styles.count}>{pendingTotal}</span>}
            </button>
            <button
              className={`${styles.tab} ${tab === "posts" ? styles.tabActive : ""}`}
              onClick={() => setTab("posts")}
            >
              Postagens
            </button>
          </div>
          <button
            className={styles.syncButton}
            onClick={runSync}
            disabled={syncing || disabled}
            title={disabled ? `Configure a conexão com o ${config.name} primeiro` : ""}
          >
            <IconRepeat size={15} /> {syncing ? "Sincronizando..." : "Sincronizar"}
          </button>
        </div>
      </div>

      {banner}
      {syncMsg && <p className={styles.syncMsg}>{syncMsg}</p>}
      {error && <p className="error-text">{error}</p>}

      {tab === "queue" && queue && (
        <>
          {queue.comments.length > 0 && (
            <div className={styles.queueToolbar}>
              <span className={styles.toolbarLabel}>Ordenar</span>
              <div className={styles.tabs} role="group" aria-label="Ordem dos comentários">
                {(
                  [
                    ["newest", "Mais novos primeiro"],
                    ["oldest", "Mais antigos primeiro"],
                  ] as [Order, string][]
                ).map(([value, label]) => (
                  <button
                    key={value}
                    className={`${styles.tab} ${order === value ? styles.tabActive : ""}`}
                    onClick={() => changeOrder(value)}
                    aria-pressed={order === value}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {queue.comments.length === 0 ? (
            <EmptyState
              icon={<IconInbox size={26} />}
              title="Nenhum comentário para aprovar"
              description={`Quando alguém comentar nas postagens do ${config.name}, o rascunho da IA aparece aqui. Use Sincronizar para buscar comentários dos últimos 7 dias.`}
            />
          ) : (
            <div className={styles.queue}>
              {queue.comments.map((c) => (
                <CommentCard
                  key={c.comment_id}
                  comment={c}
                  post={queue.posts[c.media_id]}
                  onChange={() => load()}
                />
              ))}
            </div>
          )}
        </>
      )}

      {tab === "posts" && posts && (
        <>
          {posts.posts.length === 0 ? (
            <EmptyState
              icon={<IconGrid size={26} />}
              title="Nenhuma postagem ainda"
              description={`Clique em Sincronizar para buscar as postagens recentes do ${config.name}.`}
            />
          ) : (
            <div className={styles.grid}>
              {posts.posts.map((p) => {
                const image = p.thumbnail_url || p.media_url;
                return (
                  <Link
                    key={p.media_id}
                    href={`${config.basePath}/${encodeURIComponent(p.media_id)}`}
                    className={`card ${styles.postCard}`}
                  >
                    <div className={styles.thumbWrap}>
                      {image ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={image}
                          alt=""
                          className={styles.thumb}
                          referrerPolicy="no-referrer"
                        />
                      ) : (
                        <div className={styles.thumbEmpty}>
                          <IconPhoto size={28} />
                        </div>
                      )}
                      {!!p.pending_comments && (
                        <span className={styles.pendingBadge}>
                          {p.pending_comments} para aprovar
                        </span>
                      )}
                    </div>
                    <div className={styles.postBody}>
                      <p className={styles.caption}>
                        {p.caption || (p.synced_at ? "Sem legenda" : "Detalhes não sincronizados")}
                      </p>
                      <p className={styles.meta}>
                        {p.comments_count ?? p.tracked_comments ?? 0} comentários
                        {p.posted_at && ` · ${relativeTime(p.posted_at)}`}
                      </p>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
