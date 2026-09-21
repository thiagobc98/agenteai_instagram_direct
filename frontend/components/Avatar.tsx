"use client";

import { useState } from "react";
import { avatarHue } from "../lib/format";
import { IconUser } from "./icons";
import styles from "./Avatar.module.css";

export default function Avatar({
  seed,
  size = 40,
  src,
}: {
  seed: string;
  size?: number;
  // Foto de perfil do Instagram. Se faltar ou a URL expirar, mostra o ícone.
  src?: string | null;
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const hue = avatarHue(seed);
  const showPhoto = !!src && src !== failedSrc;

  return (
    <div
      className={styles.avatar}
      style={{
        width: size,
        height: size,
        background: `hsl(${hue} 65% 94%)`,
        color: `hsl(${hue} 45% 32%)`,
      }}
    >
      {showPhoto ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          referrerPolicy="no-referrer"
          className={styles.photo}
          onError={() => setFailedSrc(src)}
        />
      ) : (
        <IconUser size={Math.round(size * 0.55)} />
      )}
    </div>
  );
}
