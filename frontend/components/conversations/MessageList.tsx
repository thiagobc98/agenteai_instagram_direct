"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage, CommentDmReply } from "../../lib/api";
import { formatDateSeparator, formatTime } from "../../lib/format";
import MessageBubble, { type BubbleData } from "./MessageBubble";
import EmptyState from "../EmptyState";
import { IconChats } from "../icons";
import styles from "./MessageList.module.css";

interface Group {
  dateKey: string;
  dateLabel: string;
  bubbles: BubbleData[];
}

/** Bolhas de um item da linha do tempo, com o instante que o posiciona. */
interface TimelineItem {
  at: string | null;
  bubbles: BubbleData[];
}

function fromQueue(msg: ChatMessage): TimelineItem {
  const bubbles: BubbleData[] = [
    {
      id: `${msg.id}-user`,
      side: "user",
      text: msg.incoming_message || msg.normalized_input || "",
      time: formatTime(msg.created_at),
      mediaType: msg.media_type,
    },
  ];

  if (msg.status === "failed") {
    bubbles.push({
      id: `${msg.id}-agent`,
      side: "agent",
      text: msg.response || "",
      time: formatTime(msg.processed_at ?? msg.created_at),
      failed: true,
      errorText: msg.error || msg.media_processing_error || "Falha no processamento",
    });
  } else if (msg.status === "done") {
    bubbles.push({
      id: `${msg.id}-agent`,
      side: "agent",
      text: msg.response || "",
      time: formatTime(msg.processed_at),
    });
  } else {
    bubbles.push({
      id: `${msg.id}-agent`,
      side: "agent",
      text: msg.status === "processing" ? "Processando..." : "Na fila...",
      time: formatTime(msg.created_at),
      pending: true,
    });
  }

  return { at: msg.created_at ?? msg.processed_at, bubbles };
}

/** Comentário no post (contexto) + mensagem privada enviada no Direct. */
function fromComment(reply: CommentDmReply): TimelineItem {
  return {
    at: reply.commented_at ?? reply.sent_at,
    bubbles: [
      {
        id: `c-${reply.comment_id}-user`,
        side: "user",
        text: reply.comment_text,
        time: formatTime(reply.commented_at),
        label: "Comentou no post",
        href: reply.post_permalink,
        variant: "comment",
      },
      {
        id: `c-${reply.comment_id}-agent`,
        side: "agent",
        text: reply.private_text,
        time: formatTime(reply.sent_at),
        label: reply.approved_by
          ? `Resposta ao comentário · aprovada por ${reply.approved_by}`
          : "Resposta ao comentário",
      },
    ],
  };
}

function buildGroups(messages: ChatMessage[], replies: CommentDmReply[]): Group[] {
  const items = [...messages.map(fromQueue), ...replies.map(fromComment)];
  // Ordem cronológica (a API devolve cada lista da mais recente para a mais antiga)
  items.sort((a, b) => new Date(a.at ?? 0).getTime() - new Date(b.at ?? 0).getTime());

  const groups: Group[] = [];
  for (const item of items) {
    const dateKey = item.at ? new Date(item.at).toDateString() : "unknown";
    let group = groups.find((g) => g.dateKey === dateKey);
    if (!group) {
      group = { dateKey, dateLabel: formatDateSeparator(item.at), bubbles: [] };
      groups.push(group);
    }
    group.bubbles.push(...item.bubbles);
  }
  return groups;
}

export default function MessageList({
  messages,
  commentReplies = [],
}: {
  messages: ChatMessage[];
  commentReplies?: CommentDmReply[];
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const total = messages.length + commentReplies.length;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [total]);

  if (total === 0) {
    return (
      <EmptyState
        icon={<IconChats size={22} />}
        title="Nenhuma mensagem para este contato"
        description="As mensagens trocadas com este número aparecerão aqui."
      />
    );
  }

  const groups = buildGroups(messages, commentReplies);

  return (
    <div className={styles.list}>
      {groups.map((group) => (
        <div key={group.dateKey}>
          <div className={styles.separator}>
            <span>{group.dateLabel}</span>
          </div>
          {group.bubbles.map((bubble) => (
            <MessageBubble key={bubble.id} data={bubble} />
          ))}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
