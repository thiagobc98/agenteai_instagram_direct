"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type PostComment, type PostDetailResponse } from "../../../../lib/api";
import { relativeTime } from "../../../../lib/format";
import CommentCard from "../../../../components/comments/CommentCard";
import EmptyState from "../../../../components/EmptyState";
import {
  IconArrowLeft,
  IconChats,
  IconExternal,
  IconPhoto,
} from "../../../../components/icons";
import styles from "./page.module.css";

type Filter = "open" | "all";

const OPEN = new Set(["new", "drafting", "pending", "failed", "sending"]);
const POLL_MS = 5000;

export default function PostDetailPage() {
  const { mediaId } = useParams<{ mediaId: string }>();
  const [data, setData] = useState<PostDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("open");

  const load = useCallback(async () => {
    try {
      setData(await api.post(decodeURIComponent(mediaId)));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar");
    }
  }, [mediaId]);

  useEffect(() => {
    load();
  }, [load]);

  const drafting = data?.comments.some((c) => c.status === "new" || c.status === "drafting");
  useEffect(() => {
    if (!drafting) return;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [drafting, load]);

  function replace(updated: PostComment) {
    setData((d) =>
      d && {
        ...d,
        comments: d.comments.map((c) => (c.comment_id === updated.comment_id ? updated : c)),
      },
    );
  }

  const openCount = useMemo(
    () => data?.comments.filter((c) => OPEN.has(c.status)).length ?? 0,
    [data],
  );
  const visible = useMemo(
    () =>
      (data?.comments ?? []).filter((c) => filter === "all" || OPEN.has(c.status)),
    [data, filter],
  );

  const post = data?.post;
  const image = post?.thumbnail_url || post?.media_url;

  return (
    <div className={styles.page}>
      <Link href="/posts" className={styles.back}>
        <IconArrowLeft size={16} /> Postagens
      </Link>

      {error && <p className="error-text">{error}</p>}

      {post && (
        <div className={styles.layout}>
          <aside className={`card ${styles.postCard}`}>
            <div className={styles.media}>
              {image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={image} alt="" referrerPolicy="no-referrer" />
              ) : (
                <div className={styles.mediaEmpty}>
                  <IconPhoto size={32} />
                </div>
              )}
            </div>
            <div className={styles.postInfo}>
              <p className={styles.caption}>
                {post.caption || (post.synced_at ? "Sem legenda" : "Detalhes não sincronizados")}
              </p>
              <p className={styles.meta}>
                {post.comments_count ?? data.comments.length} comentários
                {post.posted_at && ` · publicada ${relativeTime(post.posted_at)}`}
              </p>
              {post.permalink && (
                <a href={post.permalink} target="_blank" rel="noreferrer" className={styles.link}>
                  Ver no Instagram <IconExternal size={13} />
                </a>
              )}
            </div>
          </aside>

          <section className={styles.comments}>
            <div className={styles.commentsHeader}>
              <h2 className={styles.section}>Comentários</h2>
              <div className={styles.tabs} role="group" aria-label="Filtro">
                <button
                  className={`${styles.tab} ${filter === "open" ? styles.tabActive : ""}`}
                  onClick={() => setFilter("open")}
                >
                  Para aprovar ({openCount})
                </button>
                <button
                  className={`${styles.tab} ${filter === "all" ? styles.tabActive : ""}`}
                  onClick={() => setFilter("all")}
                >
                  Todos ({data.comments.length})
                </button>
              </div>
            </div>

            {visible.length === 0 ? (
              <EmptyState
                icon={<IconChats size={26} />}
                title={filter === "open" ? "Tudo respondido por aqui" : "Nenhum comentário registrado"}
                description={
                  filter === "open"
                    ? "Nenhum comentário desta postagem está aguardando aprovação."
                    : "Os comentários chegam pelo webhook ou pela sincronização."
                }
              />
            ) : (
              <div className={styles.list}>
                {visible.map((c) => (
                  <CommentCard key={c.comment_id} comment={c} onChange={replace} />
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
