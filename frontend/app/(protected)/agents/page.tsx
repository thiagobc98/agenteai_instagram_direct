"use client";

import { useEffect, useState } from "react";
import { api } from "../../../lib/api";
import { formatAgentName } from "../../../lib/format";
import { IconAgents } from "../../../components/icons";
import EmptyState from "../../../components/EmptyState";
import styles from "./page.module.css";

export default function AgentsPage() {
  const [agents, setAgents] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .agents()
      .then((data) => setAgents(data.agents))
      .catch((e) => setError(e.message))
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className={styles.wrap}>
      <h1 className={styles.title}>Agentes</h1>
      {error && <p className="error-text">{error}</p>}

      {loaded && agents.length === 0 && !error && (
        <EmptyState
          icon={<IconAgents size={26} />}
          title="Nenhum agente registrado"
          description="Agentes cadastrados no catálogo do backend aparecerão aqui."
        />
      )}

      {agents.length > 0 && (
        <div className={styles.grid}>
          {agents.map((agentId) => (
            <div key={agentId} className={`card ${styles.agentCard}`}>
              <div className={styles.iconWrap}>
                <IconAgents size={20} />
              </div>
              <div>
                <p className={styles.agentId}>{formatAgentName(agentId)}</p>
                <p className={styles.agentSub}>Agente ativo no catálogo</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
