// Ícones inline (SVG, stroke-based). Evita adicionar dependência de ícones
// externa só para este redesign — mantém o bundle enxuto e consistente.

import type { ReactNode } from "react";

export type IconProps = {
  size?: number;
  className?: string;
};

function base(paths: ReactNode, { size = 18, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {paths}
    </svg>
  );
}

export const IconDashboard = (p: IconProps = {}) =>
  base(
    <>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </>,
    p,
  );

export const IconChats = (p: IconProps = {}) =>
  base(
    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />,
    p,
  );

export const IconAgents = (p: IconProps = {}) =>
  base(
    <>
      <rect x="5" y="7" width="14" height="11" rx="2.5" />
      <path d="M9 7V5.5a3 3 0 0 1 6 0V7" />
      <circle cx="9.5" cy="12.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.5" cy="12.5" r="1" fill="currentColor" stroke="none" />
      <path d="M9 16h6" />
    </>,
    p,
  );

export const IconSearch = (p: IconProps = {}) =>
  base(
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </>,
    p,
  );

export const IconSend = (p: IconProps = {}) =>
  base(<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />, p);

export const IconPaperclip = (p: IconProps = {}) =>
  base(
    <path d="M21.4 11.1 12.3 20a5.2 5.2 0 0 1-7.4-7.4l9.2-9.2a3.5 3.5 0 0 1 5 5l-9.2 9.2a1.8 1.8 0 0 1-2.5-2.5l8.5-8.5" />,
    p,
  );

export const IconUser = (p: IconProps = {}) =>
  base(
    <>
      <circle cx="12" cy="8" r="3.6" />
      <path d="M4.5 20.2a7.5 7.5 0 0 1 15 0" />
    </>,
    p,
  );

export const IconLogout = (p: IconProps = {}) =>
  base(
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </>,
    p,
  );

export const IconArrowLeft = (p: IconProps = {}) =>
  base(
    <>
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </>,
    p,
  );

export const IconClock = (p: IconProps = {}) =>
  base(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.2 2" />
    </>,
    p,
  );

export const IconAlertCircle = (p: IconProps = {}) =>
  base(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5" />
      <circle cx="12" cy="16.2" r="0.3" fill="currentColor" />
    </>,
    p,
  );

export const IconCheck = (p: IconProps = {}) => base(<path d="M20 6 9 17l-5-5" />, p);

export const IconInbox = (p: IconProps = {}) =>
  base(
    <>
      <path d="M3 12h4.5l2 3h5l2-3H21" />
      <path d="M5.5 5h13l2.5 7v7a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19v-7l2.5-7Z" />
    </>,
    p,
  );

export const IconInfo = (p: IconProps = {}) =>
  base(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5" />
      <circle cx="12" cy="8" r="0.3" fill="currentColor" />
    </>,
    p,
  );

export const IconMenu = (p: IconProps = {}) =>
  base(
    <>
      <path d="M4 6h16" />
      <path d="M4 12h16" />
      <path d="M4 18h16" />
    </>,
    p,
  );

export const IconX = (p: IconProps = {}) =>
  base(
    <>
      <path d="m18 6-12 12" />
      <path d="m6 6 12 12" />
    </>,
    p,
  );

export const IconPhoto = (p: IconProps = {}) =>
  base(
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="1.7" />
      <path d="m21 16-5.5-5.5L4 21" />
    </>,
    p,
  );

export const IconMic = (p: IconProps = {}) =>
  base(
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
    </>,
    p,
  );

export const IconCalendar = (p: IconProps = {}) =>
  base(
    <>
      <rect x="3.5" y="4.5" width="17" height="16" rx="2" />
      <path d="M3.5 9.5h17" />
      <path d="M8 3v3" />
      <path d="M16 3v3" />
    </>,
    p,
  );

export const IconChevronLeft = (p: IconProps = {}) => base(<path d="m14.5 5-7 7 7 7" />, p);

export const IconChevronRight = (p: IconProps = {}) => base(<path d="m9.5 5 7 7-7 7" />, p);

export const IconLock = (p: IconProps = {}) =>
  base(
    <>
      <rect x="5" y="10.5" width="14" height="9.5" rx="2" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </>,
    p,
  );

export const IconCross = (p: IconProps = {}) =>
  base(
    <>
      <path d="M12 4v16" />
      <path d="M4 12h16" />
    </>,
    p,
  );
