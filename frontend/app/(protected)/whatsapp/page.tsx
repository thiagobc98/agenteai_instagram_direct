"use client";

// Conexão do WhatsApp (Wuzapi) que avisa o atendente a cada mensagem nova no
// Direct, e as configurações desses avisos.

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AttendantNotification,
  type NotifySettings,
  type WhatsappConnection,
} from "../../../lib/api";
import { formatPhone, relativeTime } from "../../../lib/format";
import {
  IconAlertCircle,
  IconBell,
  IconCheck,
  IconLogout,
  IconQr,
  IconSend,
  IconTrash,
} from "../../../components/icons";
import styles from "./page.module.css";

const STATUS_MS = 3000;
const HISTORY_MS = 10000;
const MAX_RECIPIENTS = 5;

const NOTIFY_STATUS: Record<AttendantNotification["status"], { label: string; tone: string }> = {
  pending: { label: "Na fila", tone: "neutral" },
  sending: { label: "Enviando", tone: "neutral" },
  sent: { label: "Enviado", tone: "success" },
  failed: { label: "Falhou", tone: "danger" },
  skipped: { label: "Não enviado", tone: "warning" },
};

export default function WhatsappPage() {
  const [connection, setConnection] = useState<WhatsappConnection | null>(null);
  const [settings, setSettings] = useState<NotifySettings | null>(null);
  const [history, setHistory] = useState<AttendantNotification[]>([]);
  const [busy, setBusy] = useState<"connect" | "disconnect" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const data = await api.whatsappStatus();
      setConnection(data.connection);
      setSettings((current) => current ?? data.settings);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar");
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      setHistory((await api.attendantNotifications()).notifications);
    } catch {
      // histórico é secundário: o erro principal aparece no status
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadHistory();
    const a = setInterval(loadStatus, STATUS_MS);
    const b = setInterval(loadHistory, HISTORY_MS);
    return () => {
      clearInterval(a);
      clearInterval(b);
    };
  }, [loadStatus, loadHistory]);

  async function connect() {
    setBusy("connect");
    setError(null);
    try {
      setConnection((await api.whatsappConnect()).connection);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao conectar");
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    if (!window.confirm("Desconectar este WhatsApp? Os avisos param até conectar de novo.")) return;
    setBusy("disconnect");
    setError(null);
    try {
      setConnection((await api.whatsappDisconnect()).connection);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao desconectar");
    } finally {
      setBusy(null);
    }
  }

  const ready = !!connection?.logged_in;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>
          <IconQr size={26} /> Conexão WhatsApp
        </h1>
        <span className={styles.refresh}>Atualiza sozinho a cada 3 segundos</span>
      </div>

      {error && (
        <p className={styles.errorBox}>
          <IconAlertCircle size={16} /> {error}
        </p>
      )}

      <div className={styles.top}>
        <section className={`card ${styles.connectionCard}`}>
          <div className={styles.cardHead}>
            <h2 className={styles.cardTitle}>WhatsApp de avisos</h2>
            <StatusBadge connection={connection} />
          </div>
          <p className={styles.cardSub}>
            Este número manda ao celular do atendente um aviso a cada mensagem nova no Direct.
          </p>

          <div className={styles.stage}>
            <ConnectionStage connection={connection} />
          </div>

          <div className={styles.actions}>
            {ready ? (
              <button className={styles.ghost} onClick={disconnect} disabled={busy !== null}>
                <IconLogout size={16} /> {busy === "disconnect" ? "Desconectando..." : "Desconectar"}
              </button>
            ) : (
              connection?.configured &&
              connection.online &&
              !connection.connected && (
                <button onClick={connect} disabled={busy !== null}>
                  {busy === "connect" ? "Conectando..." : "Conectar"}
                </button>
              )
            )}
          </div>
        </section>

        <aside className={`card ${styles.howto}`}>
          <h2 className={styles.cardTitle}>Como conectar</h2>
          <ol className={styles.steps}>
            <li>Clique em Conectar.</li>
            <li>No celular que vai ENVIAR os avisos, abra o WhatsApp.</li>
            <li>
              Toque em <strong>Mais opções</strong> (⋮) ou <strong>Configurações</strong> e depois
              em <strong>Dispositivos conectados</strong>.
            </li>
            <li>
              Toque em <strong>Conectar dispositivo</strong> e aponte a câmera para o QR Code.
            </li>
            <li>Quando aparecer &quot;Conectado&quot;, use &quot;Enviar teste&quot; abaixo.</li>
          </ol>
          <p className={styles.note}>
            Use um número diferente do celular do atendente: o WhatsApp não toca notificação
            para mensagens que você manda para si mesmo.
          </p>
        </aside>
      </div>

      {settings && (
        <NotifySettingsCard
          initial={settings}
          canTest={ready}
          onSaved={(s) => setSettings(s)}
        />
      )}

      <section className={`card ${styles.historyCard}`}>
        <h2 className={styles.cardTitle}>Últimos avisos</h2>
        {history.length === 0 ? (
          <p className={styles.empty}>Nenhum aviso ainda. Eles aparecem aqui quando chegar mensagem no Direct.</p>
        ) : (
          <ul className={styles.history}>
            {history.map((n) => {
              const st = NOTIFY_STATUS[n.status];
              return (
                <li key={n.id} className={styles.historyItem}>
                  <div className={styles.historyMain}>
                    <strong>{n.username ? `@${n.username}` : "Cliente"}</strong>
                    <span className={styles.preview}>{n.preview}</span>
                    {n.error && <span className={styles.historyError}>{n.error}</span>}
                  </div>
                  <span className={`${styles.badge} ${styles[st.tone]}`}>{st.label}</span>
                  <span className={styles.when}>{relativeTime(n.created_at)}</span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function StatusBadge({ connection }: { connection: WhatsappConnection | null }) {
  if (!connection) return null;
  if (connection.logged_in) return <span className={`${styles.badge} ${styles.success}`}>Conectado</span>;
  if (connection.qr_code) return <span className={`${styles.badge} ${styles.warning}`}>Aguardando QR Code</span>;
  if (!connection.configured || !connection.online)
    return <span className={`${styles.badge} ${styles.danger}`}>Indisponível</span>;
  return <span className={`${styles.badge} ${styles.neutral}`}>Desconectado</span>;
}

function ConnectionStage({ connection }: { connection: WhatsappConnection | null }) {
  if (!connection) return <p className={styles.muted}>Carregando...</p>;

  if (connection.logged_in) {
    return (
      <>
        <span className={styles.okCircle}>
          <IconCheck size={36} />
        </span>
        <p className={styles.stageTitle}>WhatsApp conectado</p>
        <p className={styles.muted}>{formatPhone(connection.number)}</p>
      </>
    );
  }
  if (connection.qr_code) {
    return (
      <>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={connection.qr_code} alt="QR Code para conectar o WhatsApp" className={styles.qr} />
        <p className={styles.muted}>Leia com o WhatsApp do celular que vai enviar os avisos</p>
      </>
    );
  }
  if (connection.connected) {
    return <p className={styles.muted}>Gerando o QR Code...</p>;
  }
  return (
    <>
      <span className={styles.offCircle}>
        <IconQr size={34} />
      </span>
      <p className={styles.stageTitle}>
        {!connection.configured
          ? "Wuzapi não configurado"
          : !connection.online
            ? "Wuzapi fora do ar"
            : "WhatsApp desconectado"}
      </p>
      <p className={styles.muted}>
        {connection.error ?? "Clique em Conectar para gerar o QR Code."}
      </p>
    </>
  );
}

function NotifySettingsCard({
  initial,
  canTest,
  onSaved,
}: {
  initial: NotifySettings;
  canTest: boolean;
  onSaved: (s: NotifySettings) => void;
}) {
  const [enabled, setEnabled] = useState(initial.enabled);
  const [phones, setPhones] = useState<string[]>(
    initial.recipients.length ? initial.recipients.map(formatPhone) : [""],
  );
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const saved =
    enabled === initial.enabled &&
    JSON.stringify(phones.map((p) => p.replace(/\D/g, "")).filter(Boolean)) ===
      JSON.stringify(initial.recipients.map((p) => p.replace(/\D/g, "")));

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const { settings } = await api.saveNotifySettings(
        enabled,
        phones.filter((p) => p.trim()),
      );
      onSaved(settings);
      setPhones(settings.recipients.length ? settings.recipients.map(formatPhone) : [""]);
      setMessage({ ok: true, text: "Salvo" });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : "Erro ao salvar" });
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setTesting(true);
    setMessage(null);
    try {
      const { results } = await api.sendNotifyTest();
      const failed = results.filter((r) => !r.ok);
      setMessage(
        failed.length === 0
          ? { ok: true, text: "Teste enviado! Confira o WhatsApp do atendente." }
          : {
              ok: false,
              text: failed.map((r) => `${formatPhone(r.phone)}: ${r.error}`).join(" · "),
            },
      );
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : "Erro no teste" });
    } finally {
      setTesting(false);
    }
  }

  return (
    <section className={`card ${styles.settingsCard}`}>
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>
          <IconBell size={18} /> Avisos para o atendente
        </h2>
        <label className={styles.switch}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span>{enabled ? "Ligados" : "Desligados"}</span>
        </label>
      </div>
      <p className={styles.cardSub}>
        A cada mensagem nova no Direct, o atendente recebe no WhatsApp quem mandou, o que
        escreveu e o link para abrir a conversa no Instagram. Mensagens seguidas da mesma
        cliente chegam juntas em um aviso.
      </p>

      <div className={styles.phones}>
        <span className={styles.label}>Celular do atendente</span>
        {phones.map((phone, i) => (
          <div key={i} className={styles.phoneRow}>
            <input
              value={phone}
              inputMode="tel"
              placeholder="(31) 98318-1760"
              onChange={(e) => setPhones((list) => list.map((p, j) => (j === i ? e.target.value : p)))}
            />
            {phones.length > 1 && (
              <button
                className={styles.iconBtn}
                onClick={() => setPhones((list) => list.filter((_, j) => j !== i))}
                aria-label="Remover celular"
                title="Remover"
              >
                <IconTrash size={15} />
              </button>
            )}
          </div>
        ))}
        {phones.length < MAX_RECIPIENTS && (
          <button className={styles.linkBtn} onClick={() => setPhones((l) => [...l, ""])}>
            + adicionar outro celular
          </button>
        )}
      </div>

      <div className={styles.actions}>
        <button onClick={save} disabled={saving || saved}>
          {saving ? "Salvando..." : saved ? "Salvo" : "Salvar"}
        </button>
        <button
          className={styles.ghost}
          onClick={test}
          disabled={testing || !canTest || !saved || initial.recipients.length === 0}
          title={!canTest ? "Conecte o WhatsApp primeiro" : !saved ? "Salve antes de testar" : ""}
        >
          <IconSend size={15} /> {testing ? "Enviando..." : "Enviar teste"}
        </button>
        {message && (
          <span className={message.ok ? styles.okText : styles.errText}>{message.text}</span>
        )}
      </div>
    </section>
  );
}
