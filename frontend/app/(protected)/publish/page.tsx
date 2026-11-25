"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  api,
  mediaUrl,
  type Publication,
  type PublicationKind,
  type PublishingQuota,
} from "../../../lib/api";
import {
  IN_FLIGHT,
  KIND_HINT,
  KIND_LABEL,
  STATUS_LABEL,
  formatDateTime,
} from "../../../lib/publishing";
import EmptyState from "../../../components/EmptyState";
import {
  IconAlertCircle,
  IconCalendar,
  IconPhoto,
  IconPublish,
  IconVideo,
} from "../../../components/icons";
import styles from "./page.module.css";

type Tab = "upcoming" | "published" | "all";

const POLL_MS = 8000;

export default function PublishListPage() {
  const router = useRouter();
  const [items, setItems] = useState<Publication[] | null>(null);
  const [quota, setQuota] = useState<PublishingQuota | null>(null);
  const [tab, setTab] = useState<Tab>("upcoming");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<PublicationKind | null>(null);

  const load = useCallback(async () => {
    try {
      const { publications } = await api.publications();
      setItems(publications);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar");
    }
  }, []);

  useEffect(() => {
    load();
    api.publishingQuota().then(setQuota).catch(() => {});
  }, [load]);

  const inFlight = items?.some((p) => IN_FLIGHT.includes(p.status));
  useEffect(() => {
    if (!inFlight) return;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [inFlight, load]);

  async function create(kind: PublicationKind) {
    setCreating(kind);
    try {
      const { publication } = await api.createPublication(kind);
      router.push(`/publish/${publication.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar");
      setCreating(null);
    }
  }

  const visible = useMemo(() => {
    if (!items) return [];
    if (tab === "published") return items.filter((p) => p.status === "published");
    if (tab === "upcoming") return items.filter((p) => p.status !== "published");
    return items;
  }, [items, tab]);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Publicar no Instagram</h1>
          <p className={styles.sub}>
            Suba a mídia, peça a legenda à IA, revise e publique agora ou agende.
          </p>
        </div>
        {quota?.quota_total != null && (
          <p className={styles.quota} title="Limite da Meta para publicações via API">
            {quota.quota_usage}/{quota.quota_total} publicações nas últimas 24h
          </p>
        )}
      </div>

      {quota?.public_url_problem && (
        <p className={styles.alert}>
          <IconAlertCircle size={16} /> {quota.public_url_problem} Dá para montar rascunhos,
          mas não publicar.
        </p>
      )}
      {error && <p className="error-text">{error}</p>}

      <div className={styles.newRow}>
        {(["feed", "story", "reels"] as PublicationKind[]).map((kind) => (
          <button
            key={kind}
            className={`card ${styles.newCard}`}
            onClick={() => create(kind)}
            disabled={creating !== null}
          >
            <span className={styles.newIcon}>
              {kind === "feed" ? <IconPhoto size={20} /> : <IconVideo size={20} />}
            </span>
            <span>
              <span className={styles.newTitle}>
                {creating === kind ? "Criando..." : `Novo ${KIND_LABEL[kind]}`}
              </span>
              <span className={styles.newHint}>{KIND_HINT[kind]}</span>
            </span>
          </button>
        ))}
      </div>

      <div className={styles.listHeader}>
        <div className={styles.tabs} role="group" aria-label="Filtro">
          {(
            [
              ["upcoming", "Rascunhos e agendadas"],
              ["published", "Publicadas"],
              ["all", "Todas"],
            ] as [Tab, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              className={`${styles.tab} ${tab === value ? styles.tabActive : ""}`}
              onClick={() => setTab(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {items && visible.length === 0 && (
        <EmptyState
          icon={<IconPublish size={26} />}
          title={tab === "published" ? "Nada publicado pelo painel ainda" : "Nenhum rascunho"}
          description="Comece escolhendo Feed, Story ou Reels acima."
        />
      )}

      <div className={styles.grid}>
        {visible.map((p) => {
          const status = STATUS_LABEL[p.status];
          return (
            <Link key={p.id} href={`/publish/${p.id}`} className={`card ${styles.item}`}>
              <div className={`${styles.cover} ${p.kind !== "feed" ? styles.coverTall : ""}`}>
                {p.cover_token ? (
                  p.cover_kind === "video" ? (
                    <video src={mediaUrl(p.cover_token)} muted preload="metadata" />
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={mediaUrl(p.cover_token)} alt="" />
                  )
                ) : (
                  <span className={styles.coverEmpty}>
                    <IconPhoto size={26} />
                  </span>
                )}
                {p.origin === "agent" && <span className={styles.agentTag}>Sugestão da IA</span>}
                <span className={styles.kindTag}>
                  {KIND_LABEL[p.kind]}
                  {p.kind === "feed" && (p.media_count ?? 0) > 1 && ` · ${p.media_count}`}
                </span>
              </div>
              <div className={styles.itemBody}>
                <span className={`${styles.badge} ${styles[status.tone]}`}>{status.label}</span>
                <p className={styles.caption}>
                  {p.caption || p.brief || <em className="muted">Sem legenda</em>}
                </p>
                <p className={styles.meta}>
                  <IconCalendar size={13} />
                  {p.status === "published"
                    ? `Publicada ${formatDateTime(p.published_at)}`
                    : p.publish_at && p.status !== "draft"
                      ? formatDateTime(p.publish_at)
                      : p.planned_for
                        ? `Sugerido para ${formatDateTime(p.planned_for)}`
                        : `Criada ${formatDateTime(p.created_at)}`}
                </p>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
