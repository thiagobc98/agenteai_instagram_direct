"use client";

// Prévia aproximada de como a publicação aparece no app do Instagram.
// Feed: mídia no formato da primeira foto + legenda (cortada em "mais").
// Story/Reels: tela cheia 9:16, Reels com a legenda sobreposta.

import { useState } from "react";
import { mediaUrl, type PublicationKind, type PublicationMedia } from "../../lib/api";
import { IconChevronLeft, IconChevronRight, IconPhoto } from "../icons";
import styles from "./PhonePreview.module.css";

const HANDLE = "lojapatriciaberberich";
const CAPTION_FOLD = 125;

function Media({ m, cover }: { m: PublicationMedia; cover: boolean }) {
  const style = { objectFit: cover ? ("cover" as const) : ("contain" as const) };
  return m.media_kind === "video" ? (
    <video src={mediaUrl(m.token)} style={style} muted loop autoPlay playsInline />
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={mediaUrl(m.token)} alt="" style={style} />
  );
}

export default function PhonePreview({
  kind,
  media,
  caption,
}: {
  kind: PublicationKind;
  media: PublicationMedia[];
  caption: string;
}) {
  const [index, setIndex] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const current = media[Math.min(index, media.length - 1)];
  const first = media[0];

  // Feed: o carrossel inteiro usa a proporção da primeira mídia (limitada a 4:5..1.91:1)
  let ratio = 1;
  if (first?.width && first?.height) {
    ratio = Math.min(Math.max(first.width / first.height, 0.8), 1.91);
  }

  const longCaption = caption.length > CAPTION_FOLD;
  const shownCaption =
    expanded || !longCaption ? caption : `${caption.slice(0, CAPTION_FOLD).trimEnd()}...`;

  if (kind !== "feed") {
    return (
      <div className={styles.phone}>
        <div className={styles.vertical}>
          {current ? <Media m={current} cover /> : <Empty />}
          <div className={styles.overlayTop}>
            <span className={styles.avatar} />
            <span className={styles.handle}>{HANDLE}</span>
            <span className={styles.kindTag}>{kind === "story" ? "Story" : "Reels"}</span>
          </div>
          {kind === "reels" && caption && (
            <p className={styles.overlayCaption}>{shownCaption}</p>
          )}
        </div>
        <p className={styles.note}>Prévia aproximada</p>
      </div>
    );
  }

  return (
    <div className={styles.phone}>
      <div className={styles.feed}>
        <div className={styles.feedHeader}>
          <span className={styles.avatar} />
          <span className={styles.handleDark}>{HANDLE}</span>
        </div>
        <div className={styles.feedMedia} style={{ aspectRatio: String(ratio) }}>
          {current ? <Media m={current} cover /> : <Empty />}
          {media.length > 1 && (
            <>
              <span className={styles.counter}>
                {index + 1}/{media.length}
              </span>
              {index > 0 && (
                <button
                  className={`${styles.nav} ${styles.navLeft}`}
                  onClick={() => setIndex(index - 1)}
                  aria-label="Anterior"
                >
                  <IconChevronLeft size={14} />
                </button>
              )}
              {index < media.length - 1 && (
                <button
                  className={`${styles.nav} ${styles.navRight}`}
                  onClick={() => setIndex(index + 1)}
                  aria-label="Próxima"
                >
                  <IconChevronRight size={14} />
                </button>
              )}
            </>
          )}
        </div>
        {media.length > 1 && (
          <div className={styles.dots}>
            {media.map((m, i) => (
              <span key={m.id} className={i === index ? styles.dotActive : styles.dot} />
            ))}
          </div>
        )}
        <p className={styles.feedCaption}>
          <strong>{HANDLE}</strong> {shownCaption || <em>(sem legenda)</em>}
          {longCaption && (
            <button className={styles.more} onClick={() => setExpanded(!expanded)}>
              {expanded ? "menos" : "mais"}
            </button>
          )}
        </p>
      </div>
      <p className={styles.note}>Prévia aproximada</p>
    </div>
  );
}

function Empty() {
  return (
    <span className={styles.empty}>
      <IconPhoto size={28} />
      Sem mídia
    </span>
  );
}
