"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Dashboard, type Metrics } from "../../../lib/api";
import {
  WEEKDAYS_LONG,
  WEEKDAYS_SHORT,
  contactLabel,
  formatDuration,
  formatNumber,
  formatShortDate,
  relativeTime,
} from "../../../lib/format";
import Avatar from "../../../components/Avatar";
import KpiCard from "../../../components/KpiCard";
import ChartCard from "../../../components/charts/ChartCard";
import LineChart from "../../../components/charts/LineChart";
import BarChart from "../../../components/charts/BarChart";
import HBarList from "../../../components/charts/HBarList";
import Donut from "../../../components/charts/Donut";
import chartStyles from "../../../components/charts/charts.module.css";
import { CardsSkeleton } from "../../../components/LoadingState";
import EmptyState from "../../../components/EmptyState";
import {
  IconAlertCircle,
  IconCheck,
  IconChats,
  IconClock,
  IconPhone,
  IconRepeat,
  IconTrendUp,
  IconUserPlus,
} from "../../../components/icons";
import styles from "./page.module.css";

const PERIODS = [7, 14, 30];
const REFRESH_MS = 30_000;

function argmax(values: number[]): number {
  let best = 0;
  values.forEach((v, i) => {
    if (v > values[best]) best = i;
  });
  return best;
}

function upperFirst(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function delta(today: number, yesterday: number | undefined): number | null {
  return yesterday === undefined ? null : today - yesterday;
}

export default function DashboardPage() {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<Dashboard | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    function load() {
      api
        .dashboard(days)
        .then((d) => {
          if (!cancelled) {
            setData(d);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
      api
        .metrics()
        .then((m) => !cancelled && setMetrics(m))
        .catch(() => {});
    }

    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [days]);

  const todayLabel = upperFirst(
    new Date().toLocaleDateString("pt-BR", {
      weekday: "long",
      day: "numeric",
      month: "long",
    }),
  );

  const peakHour = data ? argmax(data.by_hour) : 0;
  const busiestDay = data ? argmax(data.by_weekday) : 0;
  const topTopic = data
    ? [...data.topics].sort((a, b) => b.count - a.count)[0]
    : undefined;
  const hasActivity = !!data && data.period.messages > 0;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Visão geral da loja</h1>
          <p className={styles.date}>{todayLabel}</p>
        </div>
        <div className={styles.tabs} role="group" aria-label="Período">
          {PERIODS.map((p) => (
            <button
              key={p}
              className={`${styles.tab} ${p === days ? styles.tabActive : ""}`}
              onClick={() => setDays(p)}
            >
              {p} dias
            </button>
          ))}
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}
      {!data && !error && <CardsSkeleton />}

      {data && (
        <>
          <h2 className={styles.section}>Hoje</h2>
          <div className={styles.kpis}>
            <KpiCard
              label="Novos leads hoje"
              value={formatNumber(data.today.new_leads)}
              icon={<IconUserPlus size={22} />}
              delta={delta(data.today.new_leads, data.yesterday?.new_leads)}
              hint="pessoas que escreveram pela 1ª vez"
              tone="brand"
            />
            <KpiCard
              label="Mensagens recebidas"
              value={formatNumber(data.today.messages)}
              icon={<IconChats size={22} />}
              delta={delta(data.today.messages, data.yesterday?.messages)}
              hint={`de ${formatNumber(data.today.contacts)} cliente(s)`}
              tone="blue"
            />
            <KpiCard
              label="Encaminhados à Patrícia"
              value={formatNumber(data.today.handoff_contacts)}
              icon={<IconPhone size={22} />}
              delta={delta(
                data.today.handoff_contacts,
                data.yesterday?.handoff_contacts,
              )}
              hint={
                data.handoff_enabled
                  ? `${formatNumber(data.today.handoffs)} mensagem(ns) de encaminhamento`
                  : "defina HANDOFF_PHONE para ativar"
              }
              tone="gold"
            />
            <KpiCard
              label="Fila / falhas hoje"
              value={
                metrics
                  ? `${formatNumber(metrics.queue_size)} / ${formatNumber(metrics.failures_today)}`
                  : "-"
              }
              icon={<IconAlertCircle size={22} />}
              hint={`tempo médio ${formatDuration(metrics?.avg_processing_time_seconds ?? null)}`}
              tone={metrics && metrics.failures_today > 0 ? "danger" : "blue"}
            />
          </div>

          <h2 className={styles.section}>Últimos {days} dias</h2>
          <div className={styles.kpis}>
            <KpiCard
              label="Novos leads"
              value={formatNumber(data.period.new_leads)}
              icon={<IconTrendUp size={22} />}
              hint={`${formatNumber(data.period.total_contacts)} contatos no total`}
              tone="brand"
            />
            <KpiCard
              label="Clientes recorrentes"
              value={formatNumber(data.period.returning_contacts)}
              icon={<IconRepeat size={22} />}
              hint="já tinham falado com a loja antes"
              tone="blue"
            />
            <KpiCard
              label="Precisaram da Patrícia"
              value={`${data.period.handoff_contact_rate.toLocaleString("pt-BR")}%`}
              icon={<IconPhone size={22} />}
              hint={`${formatNumber(data.period.handoff_contacts)} de ${formatNumber(data.period.contacts)} clientes`}
              tone="gold"
            />
            <KpiCard
              label="Resolvido só pela IA"
              value={`${data.period.ai_only_rate.toLocaleString("pt-BR")}%`}
              icon={<IconClock size={22} />}
              hint="sem precisar de atendimento humano"
              tone="brand"
            />
          </div>

          {hasActivity && (
            <div className={styles.insights}>
              <div className={styles.insight}>
                <span>Horário de maior movimento</span>
                <strong>
                  {String(peakHour).padStart(2, "0")}h às{" "}
                  {String((peakHour + 1) % 24).padStart(2, "0")}h
                </strong>
              </div>
              <div className={styles.insight}>
                <span>Dia mais movimentado</span>
                <strong>{upperFirst(WEEKDAYS_LONG[busiestDay])}</strong>
              </div>
              <div className={styles.insight}>
                <span>Assunto mais perguntado</span>
                <strong>
                  {topTopic && topTopic.count > 0 ? topTopic.label : "—"}
                </strong>
              </div>
            </div>
          )}

          <div className={styles.charts}>
            <ChartCard
              title="Mensagens e novos leads por dia"
              subtitle="Volume de atendimento e chegada de clientes novas"
              span={2}
              empty={!hasActivity}
              legend={
                <div className={chartStyles.keys}>
                  <span>
                    <i
                      className={chartStyles.dot}
                      style={{ background: "var(--chart-3)" }}
                    />
                    Mensagens
                  </span>
                  <span>
                    <i
                      className={chartStyles.dot}
                      style={{ background: "var(--chart-1)" }}
                    />
                    Novos leads
                  </span>
                  <span>
                    <i
                      className={chartStyles.dot}
                      style={{ background: "var(--chart-2)" }}
                    />
                    Encaminhados
                  </span>
                </div>
              }
            >
              <LineChart
                labels={data.daily.map((d) => formatShortDate(d.date))}
                series={[
                  {
                    name: "Mensagens",
                    color: "var(--chart-3)",
                    values: data.daily.map((d) => d.messages),
                    area: true,
                  },
                  {
                    name: "Novos leads",
                    color: "var(--chart-1)",
                    values: data.daily.map((d) => d.new_leads),
                  },
                  {
                    name: "Encaminhados",
                    color: "var(--chart-2)",
                    values: data.daily.map((d) => d.handoff_contacts),
                  },
                ]}
              />
            </ChartCard>

            <ChartCard
              title="Assuntos mais perguntados"
              subtitle="O que as clientes querem saber"
              empty={!hasActivity}
            >
              <HBarList
                items={[...data.topics]
                  .sort((a, b) => b.count - a.count)
                  .map((t) => ({ label: t.label, value: t.count }))}
              />
            </ChartCard>

            <ChartCard
              title="Horários de maior movimento"
              subtitle="Mensagens por hora do dia (horário de Brasília)"
              span={2}
              empty={!hasActivity}
            >
              <BarChart
                values={data.by_hour}
                labels={data.by_hour.map((_, h) => `${h}h`)}
                labelEvery={2}
                color="var(--chart-3)"
              />
            </ChartCard>

            <ChartCard
              title="Dias da semana"
              subtitle="Quando as clientes mais escrevem"
              empty={!hasActivity}
            >
              <BarChart
                values={data.by_weekday}
                labels={WEEKDAYS_SHORT}
                width={340}
                color="var(--chart-1)"
              />
            </ChartCard>

            <ChartCard
              title="Aguardando a Patrícia"
              subtitle="Clientes encaminhados nos últimos 7 dias"
              span={2}
            >
              {data.handoff_queue.length === 0 ? (
                <EmptyState
                  icon={<IconCheck size={22} />}
                  title="Ninguém aguardando"
                  description="Quando a IA encaminhar uma cliente à Patrícia, ela aparece aqui."
                />
              ) : (
                <ul className={styles.queue}>
                  {data.handoff_queue.map((c) => (
                    <li key={c.external_id}>
                      <Link
                        href={`/chats/${encodeURIComponent(c.external_id)}`}
                        className={styles.queueItem}
                      >
                        <Avatar seed={c.external_id} size={38} src={c.profile_pic_url} />
                        <div className={styles.queueBody}>
                          <span className={styles.queueName}>{contactLabel(c)}</span>
                          <span className={styles.queueMsg}>
                            {c.last_message || "Mensagem sem texto"}
                          </span>
                        </div>
                        <span className={styles.queueTime}>{relativeTime(c.at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </ChartCard>

            <ChartCard
              title="Tipo de mensagem"
              subtitle="Texto, fotos e áudios recebidos"
              empty={!hasActivity}
            >
              <Donut
                segments={[
                  {
                    label: "Texto",
                    value: data.media.text,
                    color: "var(--chart-3)",
                  },
                  {
                    label: "Fotos",
                    value: data.media.image,
                    color: "var(--chart-1)",
                  },
                  {
                    label: "Áudios",
                    value: data.media.audio,
                    color: "var(--chart-2)",
                  },
                ]}
              />
            </ChartCard>
          </div>
        </>
      )}
    </div>
  );
}
