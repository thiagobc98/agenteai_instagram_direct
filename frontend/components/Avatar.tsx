import { avatarHue } from "../lib/format";
import { IconUser } from "./icons";
import styles from "./Avatar.module.css";

export default function Avatar({
  seed,
  size = 40,
}: {
  seed: string;
  size?: number;
}) {
  const hue = avatarHue(seed);
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
      <IconUser size={Math.round(size * 0.55)} />
    </div>
  );
}
