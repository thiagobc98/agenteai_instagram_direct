"use client";

// Chat da equipe com o agente de marketing (estrategista de conteúdo e
// crescimento). As respostas se baseiam em dados reais (ferramentas) e o
// agente pode criar rascunhos na tela Publicar, que a equipe aprova.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  type MarketingAction,
  type MarketingMessage,
  type MarketingThread,
} from "../../../lib/api";
import { relativeTime } from "../../../lib/format";
import { KIND_LABEL, formatDateTime } from "../../../lib/publishing";
import Markdown from "../../../components/Markdown";
import {
  IconCalendar,
  IconPublish,
  IconSend,
  IconSparkle,
  IconTrash,
  IconTrendUp,
} from "../../../components/icons";
import styles from "./page.module.css";

const STARTERS = [
  {
    title: "Plano da próxima semana",
    prompt:
      "Monte o plano de conteúdo da próxima semana (feed, Reels e Stories) com base nos nossos dados e já deixe os rascunhos criados.",
  },
  {
    title: "O que está funcionando?",
    prompt:
      "Analise o desempenho dos nossos últimos posts: o que está funcionando, o que não está e o que devemos fazer mais.",
  },
  {
    title: "Perguntas viram conteúdo",
    prompt:
      "O que as clientes mais perguntam no Direct e nos comentários? Transforme isso em ideias de conteúdo que tragam vendas.",
  },
  {
    title: "Trazer clientes à loja",
    prompt:
      "Quero mais clientes na loja física do Barro Preto. Que ações e conteúdos você recomenda para as próximas semanas?",
  },
  {
    title: "Próximas datas comerciais",
    prompt:
      "Quais datas comerciais estão chegando e como devemos nos preparar no Instagram para cada uma?",
  },
];

const TOOL_LABEL: Record<string, string> = {
  ver_desempenho_dos_posts: "Desempenho dos posts",
  ver_perfil_da_conta: "Perfil da conta",
  ver_demanda_das_clientes: "Demanda das clientes",
  ver_calendario_de_conteudo: "Calendário de conteúdo",
  ver_datas_comerciais: "Datas comerciais",
  criar_rascunho_de_post: "Rascunhos criados",
};

const THINKING = [
  "Consultando o desempenho dos posts...",
  "Lendo o que as clientes perguntam...",
  "Conferindo o calendário de conteúdo...",
  "Cruzando com as datas comerciais...",
  "Montando as recomendações...",
];

export default function MarketingPage() {
  const [threads, setThreads] = useState<MarketingThread[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [messages, setMessages] = useState<MarketingMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [thinking, setThinking] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  // Conversa criada pelo próprio envio: não recarrega (apagaria a pergunta
  // que já está na tela enquanto a resposta não chega)
  const justCreated = useRef<number | null>(null);

  const loadThreads = useCallback(async () => {
    try {
      setThreads((await api.marketingThreads()).threads);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar");
    }
  }, []);

  useEffect(() => {
    loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    if (active == null) {
      setMessages([]);
      return;
    }
    if (justCreated.current === active) return;
    api
      .marketingThread(active)
      .then((data) => setMessages(data.messages))
      .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar"));
  }, [active]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  useEffect(() => {
    if (!sending) return;
    setThinking(0);
    const t = setInterval(() => setThinking((n) => (n + 1) % THINKING.length), 3500);
    return () => clearInterval(t);
  }, [sending]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || sending) return;
    setError(null);
    setSending(true);
    setInput("");

    let threadId = active;
    try {
      if (threadId == null) {
        const { thread } = await api.createMarketingThread();
        threadId = thread.id;
        justCreated.current = thread.id;
        setActive(thread.id);
      }
      // Mostra a pergunta na hora (resposta pode levar ~1 min)
      setMessages((m) => [
        ...m,
        {
          id: -Date.now(),
          role: "user",
          content,
          actions: [],
          created_by: null,
          created_at: new Date().toISOString(),
        },
      ]);
      const { messages: saved } = await api.askMarketing(threadId, content);
      setMessages((m) => [...m.filter((x) => x.id > 0), ...saved]);
      loadThreads();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao enviar");
      setInput(content);
      setMessages((m) => m.filter((x) => x.id > 0));
    } finally {
      setSending(false);
    }
  }

  async function remove(id: number) {
    if (!window.confirm("Apagar esta conversa? Os rascunhos criados continuam na tela Publicar."))
      return;
    await api.deleteMarketingThread(id).catch(() => {});
    if (active === id) setActive(null);
    loadThreads();
  }

  const empty = messages.length === 0 && !sending;

  return (
    <div className={styles.page}>
      <aside className={styles.threads}>
        <button className={styles.newThread} onClick={() => setActive(null)} disabled={sending}>
          <IconSparkle size={15} /> Nova conversa
        </button>
        <div className={styles.threadList}>
          {threads.map((t) => (
            <div
              key={t.id}
              className={`${styles.thread} ${active === t.id ? styles.threadActive : ""}`}
            >
              <button
                className={styles.threadButton}
                onClick={() => !sending && setActive(t.id)}
                title={t.title}
              >
                <span className={styles.threadTitle}>{t.title}</span>
                <span className={styles.threadDate}>{relativeTime(t.updated_at)}</span>
              </button>
              <button
                className={styles.threadDelete}
                onClick={() => remove(t.id)}
                aria-label="Apagar conversa"
                title="Apagar conversa"
              >
                <IconTrash size={14} />
              </button>
            </div>
          ))}
          {threads.length === 0 && <p className={styles.noThreads}>Nenhuma conversa ainda.</p>}
        </div>
      </aside>

      <section className={styles.chat}>
        <div className={styles.messages}>
          {empty && (
            <div className={styles.intro}>
              <div className={styles.introIcon}>
                <IconTrendUp size={26} />
              </div>
              <h1 className={styles.introTitle}>Estrategista de marketing</h1>
              <p className={styles.introText}>
                Especialista em crescimento no Instagram para trazer clientes à loja. Analisa o
                desempenho dos posts, o que as clientes perguntam no Direct e as datas comerciais,
                e cria rascunhos na tela Publicar para vocês aprovarem.
              </p>
              <div className={styles.starters}>
                {STARTERS.map((s) => (
                  <button key={s.title} className={styles.starter} onClick={() => send(s.prompt)}>
                    <strong>{s.title}</strong>
                    <span>{s.prompt}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <Message key={m.id} message={m} />
          ))}

          {sending && (
            <div className={`${styles.msg} ${styles.assistant}`}>
              <div className={styles.bubble}>
                <p className={styles.thinking}>
                  <IconSparkle size={14} /> {THINKING[thinking]}
                </p>
              </div>
            </div>
          )}
          <div ref={bottom} />
        </div>

        {error && <p className={`error-text ${styles.error}`}>{error}</p>}

        <form
          className={styles.composer}
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <textarea
            value={input}
            rows={2}
            maxLength={4000}
            placeholder="Pergunte sobre conteúdo, crescimento, datas, campanhas... (Enter envia, Shift+Enter quebra linha)"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            disabled={sending}
          />
          <button type="submit" disabled={sending || !input.trim()} aria-label="Enviar">
            <IconSend size={17} />
          </button>
        </form>
      </section>
    </div>
  );
}

function Message({ message }: { message: MarketingMessage }) {
  const drafts = message.actions.filter(
    (a): a is Extract<MarketingAction, { type: "draft" }> => a.type === "draft",
  );
  const tools = message.actions.find(
    (a): a is Extract<MarketingAction, { type: "tools" }> => a.type === "tools",
  );
  const isError = message.actions.some((a) => a.type === "error");

  if (message.role === "user") {
    return (
      <div className={`${styles.msg} ${styles.user}`}>
        <div className={styles.bubble}>{message.content}</div>
      </div>
    );
  }

  return (
    <div className={`${styles.msg} ${styles.assistant}`}>
      <div className={`${styles.bubble} ${isError ? styles.bubbleError : ""}`}>
        <Markdown text={message.content} />

        {drafts.length > 0 && (
          <div className={styles.drafts}>
            <p className={styles.draftsTitle}>
              <IconPublish size={14} /> {drafts.length} rascunho{drafts.length > 1 ? "s" : ""}{" "}
              criado{drafts.length > 1 ? "s" : ""} na tela Publicar
            </p>
            {drafts.map((d) => (
              <Link key={d.publication_id} href={`/publish/${d.publication_id}`} className={styles.draft}>
                <span className={styles.draftKind}>{KIND_LABEL[d.kind] ?? d.kind}</span>
                <span className={styles.draftTitle}>{d.title}</span>
                <span className={styles.draftDate}>
                  <IconCalendar size={12} /> {formatDateTime(d.planned_for)}
                </span>
              </Link>
            ))}
          </div>
        )}

        {tools && tools.names.length > 0 && (
          <p className={styles.sources}>
            Fontes: {tools.names.map((n) => TOOL_LABEL[n] ?? n).join(" · ")}
          </p>
        )}
      </div>
    </div>
  );
}
