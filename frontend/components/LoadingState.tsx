import styles from "./LoadingState.module.css";

export function ConversationListSkeleton() {
  return (
    <div className={styles.list}>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className={styles.row}>
          <div className={`${styles.circle} ${styles.pulse}`} />
          <div className={styles.lines}>
            <div className={`${styles.bar} ${styles.pulse}`} style={{ width: "55%" }} />
            <div className={`${styles.bar} ${styles.pulse}`} style={{ width: "80%" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function MessagesSkeleton() {
  return (
    <div className={styles.messages}>
      {[1, 0, 1, 1, 0].map((side, i) => (
        <div
          key={i}
          className={`${styles.bubble} ${styles.pulse}`}
          style={{
            alignSelf: side ? "flex-end" : "flex-start",
            width: `${140 + (i % 3) * 40}px`,
          }}
        />
      ))}
    </div>
  );
}

export function CardsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className={styles.cards}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={`card ${styles.statCard}`}>
          <div className={`${styles.bar} ${styles.pulse}`} style={{ width: "60%", height: 12 }} />
          <div
            className={`${styles.bar} ${styles.pulse}`}
            style={{ width: "40%", height: 26, marginTop: 10 }}
          />
        </div>
      ))}
    </div>
  );
}
