"use client";

// Compositor de publicação: tipo, mídia, briefing, legenda (IA), validação,
// prévia e aprovação (publicar agora ou agendar).

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  mediaUrl,
  uploadPublicationMedia,
  type Publication,
  type PublicationKind,
} from "../../../../lib/api";
import {
  IN_FLIGHT,
  KIND_HINT,
  KIND_LABEL,
  MAX_CAPTION,
  MAX_HASHTAGS,
  MAX_MENTIONS,
  STATUS_LABEL,
  countHashtags,
  countMentions,
  formatBytes,
  formatDateTime,
  readVideoMeta,
  toLocalInput,
} from "../../../../lib/publishing";
import {
  IconAlertCircle,
  IconArrowLeft,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconExternal,
  IconSparkle,
  IconTrash,
  IconUpload,
} from "../../../../components/icons";
import PhonePreview from "../../../../components/publishing/PhonePreview";
import styles from "./page.module.css";

const POLL_MS = 5000;
const ACCEPT = "image/jpeg,image/png,image/webp,video/mp4,video/quicktime";

type Upload = { key: string; name: string; progress: number; error?: string };

export default function PublicationComposerPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useRouter();

  const [pub, setPub] = useState<Publication | null>(null);
  const [brief, setBrief] = useState("");
  const [caption, setCaption] = useState("");
  const [dirty, setDirty] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aiNotes, setAiNotes] = useState<string | null>(null);
  const [when, setWhen] = useState<"now" | "later">("now");
  const [publishAt, setPublishAt] = useState(() =>
    toLocalInput(new Date(Date.now() + 60 * 60 * 1000)),
  );
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const apply = useCallback((p: Publication, resetText = false) => {
    setPub(p);
    if (resetText) {
      setBrief(p.brief);
      setCaption(p.caption);
      setDirty(false);
    }
  }, []);

  const load = useCallback(
    async (resetText = false) => {
      try {
        const { publication } = await api.publication(id);
        apply(publication, resetText);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro ao carregar");
      }
    },
    [id, apply],
  );

  useEffect(() => {
    load(true);
  }, [load]);

  // Acompanha o Worker enquanto a publicação está subindo
  const inFlight = pub ? IN_FLIGHT.includes(pub.status) : false;
  useEffect(() => {
    if (!inFlight) return;
    const t = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(t);
  }, [inFlight, load]);

  // Rascunho sugerido pelo agente de marketing: já vem com o horário sugerido
  const plannedFor = pub?.planned_for ?? null;
  useEffect(() => {
    if (plannedFor && new Date(plannedFor).getTime() > Date.now()) {
      setWhen("later");
      setPublishAt(toLocalInput(new Date(plannedFor)));
    }
  }, [plannedFor]);

  const editable = pub?.status === "draft" || pub?.status === "failed";

  /** Salva briefing/legenda pendentes antes de qualquer ação no servidor. */
  async function flush(): Promise<Publication | null> {
    if (!pub || !dirty || !editable) return pub;
    const { publication } = await api.updatePublication(id, { brief, caption });
    setPub(publication);
    setDirty(false);
    return publication;
  }

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro desconhecido");
    } finally {
      setBusy(null);
    }
  }

  async function setKind(kind: PublicationKind) {
    await run("kind", async () => {
      await flush();
      const { publication } = await api.updatePublication(id, { kind });
      setPub(publication);
    });
  }

  async function addFiles(fileList: FileList | File[]) {
    if (!editable) return;
    const files = Array.from(fileList); // antes de qualquer await
    await flush().catch(() => null);
    for (const file of files) {
      const key = `${file.name}-${file.size}-${Date.now()}`;
      setUploads((u) => [...u, { key, name: file.name, progress: 0 }]);
      try {
        const meta = file.type.startsWith("video/") ? await readVideoMeta(file) : {};
        const { publication } = await uploadPublicationMedia(id, file, meta, (progress) =>
          setUploads((u) => u.map((x) => (x.key === key ? { ...x, progress } : x))),
        );
        setPub(publication);
        setUploads((u) => u.filter((x) => x.key !== key));
      } catch (e) {
        const message = e instanceof Error ? e.message : "Falha no upload";
        setUploads((u) => u.map((x) => (x.key === key ? { ...x, error: message } : x)));
      }
    }
  }

  async function move(index: number, delta: number) {
    if (!pub?.media) return;
    const ids = pub.media.map((m) => m.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await run("reorder", async () => {
      const { publication } = await api.reorderPublicationMedia(id, ids);
      setPub(publication);
    });
  }

  async function generate() {
    await run("caption", async () => {
      const fresh = await flush();
      // Pede confirmação só se a legenda atual foi escrita/editada à mão
      if (caption.trim() && fresh?.caption !== fresh?.ai_caption) {
        const ok = window.confirm("Substituir a legenda atual pela gerada pela IA?");
        if (!ok) return;
      }
      const { publication, notes } = await api.generateCaption(id);
      apply(publication, true);
      setAiNotes(notes);
    });
  }

  async function approve() {
    await run("schedule", async () => {
      await flush();
      let iso: string | null = null;
      if (when === "later") {
        const date = new Date(publishAt);
        if (Number.isNaN(date.getTime())) throw new Error("Data inválida");
        iso = date.toISOString();
      }
      const label = when === "now" ? "publicar agora" : `agendar para ${formatDateTime(iso)}`;
      if (!window.confirm(`Confirmar: ${label}? A publicação é pública e em nome da loja.`)) {
        return;
      }
      const { publication } = await api.schedulePublication(id, iso);
      apply(publication, true);
    });
  }

  async function backToDraft() {
    await run("unschedule", async () => {
      const { publication } = await api.unschedulePublication(id);
      apply(publication, true);
    });
  }

  async function discard() {
    if (!window.confirm("Descartar esta publicação? A mídia enviada será apagada.")) return;
    await run("cancel", async () => {
      await api.cancelPublication(id);
      router.push("/publish");
    });
  }

  if (!pub) {
    return (
      <div className={styles.page}>
        {error ? <p className="error-text">{error}</p> : <p className="muted">Carregando...</p>}
      </div>
    );
  }

  const media = pub.media ?? [];
  const status = STATUS_LABEL[pub.status];
  const validation = pub.validation;
  const hashtags = countHashtags(caption);
  const mentions = countMentions(caption);
  const uploading = uploads.some((u) => !u.error);
  const canApprove =
    editable &&
    !uploading &&
    !busy &&
    !!validation &&
    validation.errors.length === 0 &&
    !validation.public_url_problem;

  return (
    <div className={styles.page}>
      <div className={styles.topbar}>
        <Link href="/publish" className={styles.back}>
          <IconArrowLeft size={16} /> Publicações
        </Link>
        <span className={`${styles.badge} ${styles[status.tone]}`}>{status.label}</span>
      </div>

      {error && (
        <p className={styles.errorBox}>
          <IconAlertCircle size={15} /> {error}
        </p>
      )}

      {pub.origin === "agent" && pub.status !== "published" && (
        <div className={styles.agentBox}>
          <p className={styles.agentTitle}>
            <IconSparkle size={15} /> Sugestão do agente de marketing
            {pub.planned_for && <span> · para {formatDateTime(pub.planned_for)}</span>}
          </p>
          {pub.rationale && <p className={styles.agentText}>{pub.rationale}</p>}
          {editable && media.length === 0 && (
            <p className={styles.agentText}>
              <strong>Próximo passo:</strong> produza a mídia seguindo o briefing abaixo, suba aqui,
              revise a legenda e aprove.
            </p>
          )}
        </div>
      )}

      {pub.status === "failed" && pub.error && (
        <p className={styles.errorBox}>
          <IconAlertCircle size={15} /> Não foi publicada: {pub.error}
        </p>
      )}

      {pub.status === "published" && (
        <div className={styles.successBox}>
          <IconCheck size={16} /> Publicada {formatDateTime(pub.published_at)}
          {pub.approved_by && ` · aprovada por ${pub.approved_by}`}
          {pub.permalink && (
            <a href={pub.permalink} target="_blank" rel="noreferrer">
              Ver no Instagram <IconExternal size={13} />
            </a>
          )}
        </div>
      )}

      {IN_FLIGHT.includes(pub.status) && (
        <div className={styles.infoBox}>
          {pub.status === "scheduled" ? (
            <>
              Agendada para <strong>{formatDateTime(pub.publish_at)}</strong>
              {pub.approved_by && ` · aprovada por ${pub.approved_by}`}
              {pub.error && <span className={styles.infoNote}>{pub.error}</span>}
            </>
          ) : (
            <>
              {pub.status === "processing"
                ? "A Meta está processando a mídia (vídeo pode levar alguns minutos)..."
                : "Publicando..."}
            </>
          )}
          {pub.status === "scheduled" && (
            <button className={styles.ghost} onClick={backToDraft} disabled={!!busy}>
              Voltar para rascunho
            </button>
          )}
        </div>
      )}

      <div className={styles.layout}>
        <div className={styles.editor}>
          {/* Tipo */}
          <section className={`card ${styles.section}`}>
            <h2 className={styles.sectionTitle}>Tipo</h2>
            <div className={styles.kinds} role="radiogroup" aria-label="Tipo de publicação">
              {(["feed", "story", "reels"] as PublicationKind[]).map((kind) => (
                <button
                  key={kind}
                  role="radio"
                  aria-checked={pub.kind === kind}
                  className={`${styles.kind} ${pub.kind === kind ? styles.kindActive : ""}`}
                  onClick={() => setKind(kind)}
                  disabled={!editable || !!busy || pub.kind === kind}
                >
                  {KIND_LABEL[kind]}
                </button>
              ))}
            </div>
            <p className={styles.hint}>{KIND_HINT[pub.kind]}</p>
            {pub.kind === "reels" && (
              <label className={styles.check}>
                <input
                  type="checkbox"
                  checked={pub.share_to_feed}
                  disabled={!editable || !!busy}
                  onChange={(e) =>
                    run("share", async () => {
                      const { publication } = await api.updatePublication(id, {
                        share_to_feed: e.target.checked,
                      });
                      setPub(publication);
                    })
                  }
                />
                Mostrar também no feed (grade do perfil)
              </label>
            )}
          </section>

          {/* Mídia */}
          <section className={`card ${styles.section}`}>
            <h2 className={styles.sectionTitle}>
              Mídia {pub.kind === "feed" && media.length > 0 && `(${media.length}/10)`}
            </h2>

            {media.length > 0 && (
              <ol className={styles.mediaList}>
                {media.map((m, i) => (
                  <li key={m.id} className={styles.mediaItem}>
                    <div className={styles.thumb}>
                      {m.media_kind === "video" ? (
                        <video src={mediaUrl(m.token)} muted preload="metadata" />
                      ) : (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={mediaUrl(m.token)} alt="" />
                      )}
                    </div>
                    <div className={styles.mediaInfo}>
                      <p className={styles.mediaName}>{m.original_name || `Item ${i + 1}`}</p>
                      <p className={styles.mediaMeta}>
                        {m.media_kind === "video" ? "Vídeo" : "Foto"}
                        {m.width && m.height && ` · ${m.width}x${m.height}`}
                        {m.duration_seconds != null && ` · ${Math.round(m.duration_seconds)}s`}
                        {` · ${formatBytes(m.size_bytes)}`}
                      </p>
                    </div>
                    {editable && (
                      <div className={styles.mediaActions}>
                        {media.length > 1 && (
                          <>
                            <button
                              className={styles.iconBtn}
                              onClick={() => move(i, -1)}
                              disabled={i === 0 || !!busy}
                              title="Mover para antes"
                              aria-label="Mover para antes"
                            >
                              <IconChevronLeft size={15} />
                            </button>
                            <button
                              className={styles.iconBtn}
                              onClick={() => move(i, 1)}
                              disabled={i === media.length - 1 || !!busy}
                              title="Mover para depois"
                              aria-label="Mover para depois"
                            >
                              <IconChevronRight size={15} />
                            </button>
                          </>
                        )}
                        <button
                          className={styles.iconBtn}
                          onClick={() =>
                            run("remove", async () => {
                              const { publication } = await api.removePublicationMedia(id, m.id);
                              setPub(publication);
                            })
                          }
                          disabled={!!busy}
                          title="Remover"
                          aria-label="Remover"
                        >
                          <IconTrash size={15} />
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}

            {uploads.map((u) => (
              <div key={u.key} className={styles.upload}>
                <span className={styles.uploadName}>{u.name}</span>
                {u.error ? (
                  <span className={styles.uploadError}>
                    {u.error}
                    <button
                      className={styles.linkBtn}
                      onClick={() => setUploads((x) => x.filter((y) => y.key !== u.key))}
                    >
                      fechar
                    </button>
                  </span>
                ) : (
                  <span className={styles.progress}>
                    <span style={{ width: `${Math.round(u.progress * 100)}%` }} />
                  </span>
                )}
              </div>
            ))}

            {editable && (pub.kind === "feed" ? media.length < 10 : media.length < 1) && (
              <div
                className={`${styles.drop} ${dragOver ? styles.dropOver : ""}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  addFiles(e.dataTransfer.files);
                }}
                onClick={() => fileInput.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && fileInput.current?.click()}
              >
                <IconUpload size={22} />
                <span>
                  Arraste {pub.kind === "feed" ? "fotos ou vídeos" : pub.kind === "reels" ? "o vídeo" : "a foto ou vídeo"} aqui
                  ou <u>escolha no computador</u>
                </span>
                <small>JPEG, PNG, WebP, MP4 ou MOV</small>
                <input
                  ref={fileInput}
                  type="file"
                  accept={ACCEPT}
                  multiple={pub.kind === "feed"}
                  hidden
                  onChange={(e) => {
                    // Copia antes de limpar o input: o FileList é "vivo" e
                    // esvazia junto com o value.
                    const files = Array.from(e.target.files ?? []);
                    e.target.value = "";
                    if (files.length) addFiles(files);
                  }}
                />
              </div>
            )}
          </section>

          {/* Legenda */}
          {pub.kind !== "story" ? (
            <section className={`card ${styles.section}`}>
              <h2 className={styles.sectionTitle}>Legenda</h2>
              <label className={styles.field}>
                <span className={styles.label}>
                  Briefing para a IA <small>o que destacar, tom, promoção, público</small>
                </span>
                <textarea
                  rows={2}
                  value={brief}
                  maxLength={4000}
                  placeholder="Ex: lançamento do scarpin Bianca, nude, linha conforto. Tom elegante."
                  disabled={!editable}
                  onChange={(e) => {
                    setBrief(e.target.value);
                    setDirty(true);
                  }}
                  onBlur={() => flush().catch(() => {})}
                />
              </label>
              <button
                className={styles.aiButton}
                onClick={generate}
                disabled={!editable || !!busy || uploading}
              >
                <IconSparkle size={15} />
                {busy === "caption" ? "A IA está escrevendo..." : "Gerar legenda com IA"}
              </button>
              {aiNotes && <p className={styles.aiNotes}>Nota da IA: {aiNotes}</p>}

              <label className={styles.field}>
                <span className={styles.label}>Texto que vai ao ar</span>
                <textarea
                  rows={9}
                  value={caption}
                  disabled={!editable}
                  onChange={(e) => {
                    setCaption(e.target.value);
                    setDirty(true);
                  }}
                  onBlur={() => flush().catch(() => {})}
                />
                <span className={styles.counters}>
                  <span className={caption.length > MAX_CAPTION ? styles.over : ""}>
                    {caption.length}/{MAX_CAPTION}
                  </span>
                  <span className={hashtags > MAX_HASHTAGS ? styles.over : ""}>
                    {hashtags}/{MAX_HASHTAGS} hashtags
                  </span>
                  <span className={mentions > MAX_MENTIONS ? styles.over : ""}>
                    {mentions}/{MAX_MENTIONS} menções
                  </span>
                </span>
              </label>
            </section>
          ) : (
            <section className={`card ${styles.section}`}>
              <h2 className={styles.sectionTitle}>Legenda</h2>
              <p className={styles.hint}>
                Story não tem legenda pela API: textos, figurinhas e links precisam estar na
                própria imagem ou vídeo.
              </p>
            </section>
          )}

          {/* Aprovação */}
          {editable && (
            <section className={`card ${styles.section}`}>
              <h2 className={styles.sectionTitle}>Publicar</h2>

              {validation && (validation.errors.length > 0 || validation.public_url_problem) && (
                <ul className={styles.errors}>
                  {validation.public_url_problem && <li>{validation.public_url_problem}</li>}
                  {validation.errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              )}
              {validation && validation.warnings.length > 0 && (
                <ul className={styles.warnings}>
                  {validation.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
              {dirty && <p className={styles.hint}>Alterações não salvas: serão salvas ao aprovar.</p>}

              <div className={styles.when} role="radiogroup" aria-label="Quando publicar">
                <label className={styles.check}>
                  <input
                    type="radio"
                    name="when"
                    checked={when === "now"}
                    onChange={() => setWhen("now")}
                  />
                  Publicar agora
                </label>
                <label className={styles.check}>
                  <input
                    type="radio"
                    name="when"
                    checked={when === "later"}
                    onChange={() => setWhen("later")}
                  />
                  Agendar
                </label>
                {when === "later" && (
                  <input
                    type="datetime-local"
                    value={publishAt}
                    min={toLocalInput(new Date())}
                    onChange={(e) => setPublishAt(e.target.value)}
                  />
                )}
              </div>

              <div className={styles.actions}>
                <button onClick={approve} disabled={!canApprove}>
                  {busy === "schedule"
                    ? "Enviando..."
                    : when === "now"
                      ? "Aprovar e publicar agora"
                      : "Aprovar e agendar"}
                </button>
                <button className={styles.ghost} onClick={discard} disabled={!!busy}>
                  Descartar
                </button>
              </div>
            </section>
          )}
        </div>

        <aside className={styles.previewCol}>
          <PhonePreview kind={pub.kind} media={media} caption={caption} />
          {pub.created_by && (
            <p className={styles.audit}>
              Criada por {pub.created_by} em {formatDateTime(pub.created_at)}
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
