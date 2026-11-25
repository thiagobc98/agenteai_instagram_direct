"use client";

// Comentários dos posts da Página do Facebook (fila de aprovação + posts).
// Mesmo fluxo do Instagram: a IA rascunha, a equipe aprova; a mensagem
// privada vai pelo Messenger da Página.

import { useEffect, useState } from "react";
import { api, type FacebookStatus } from "../../../lib/api";
import CommentsWorkspace from "../../../components/comments/CommentsWorkspace";
import { IconAlertCircle, IconCheck } from "../../../components/icons";
import styles from "./page.module.css";

export default function FacebookPage() {
  const [status, setStatus] = useState<FacebookStatus | null>(null);

  useEffect(() => {
    api
      .facebookStatus()
      .then(setStatus)
      .catch((e) =>
        setStatus({
          configured: false,
          missing: [],
          page: null,
          error: e instanceof Error ? e.message : "Erro ao verificar a Página",
          pending_total: 0,
        }),
      );
  }, []);

  const ready = !!status?.configured && !!status.page && !status.error;

  return (
    <CommentsWorkspace
      channel="facebook"
      title="Comentários do Facebook"
      subtitle="Comentários dos posts da Página. A IA escreve um rascunho; revise e aprove antes de publicar."
      sync={api.syncFacebook}
      disabled={!ready}
      banner={status && <StatusBanner status={status} />}
    />
  );
}

function StatusBanner({ status }: { status: FacebookStatus }) {
  if (status.configured && status.page && !status.error) {
    return (
      <p className={`${styles.banner} ${styles.ok}`}>
        <IconCheck size={15} /> Conectado à Página <strong>{status.page.name}</strong>
        {status.missing.includes("FACEBOOK_APP_SECRET") && (
          <span className={styles.warnInline}>
            · falta FACEBOOK_APP_SECRET: o webhook não recebe comentários em tempo real
          </span>
        )}
      </p>
    );
  }
  return (
    <div className={`${styles.banner} ${styles.warn}`}>
      <p className={styles.bannerTitle}>
        <IconAlertCircle size={15} />{" "}
        {status.configured ? "Problema na conexão com a Página" : "Página do Facebook não conectada"}
      </p>
      {status.error && <p className={styles.bannerText}>{status.error}</p>}
      {status.missing.length > 0 && (
        <p className={styles.bannerText}>
          Preencha no <code>.env</code>: {status.missing.join(", ")}. Passo a passo em{" "}
          <code>docs/FACEBOOK.md</code>.
        </p>
      )}
    </div>
  );
}
