import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { toneIcons, type StatusTone } from "./statusTone";

export function StatusPill({ tone, children, label }: { tone: StatusTone; children: ReactNode; label?: string }) {
  return <span className={`status-pill status-pill--${tone}`} aria-label={label}>{<Icon name={toneIcons[tone]} size={14} />}<span>{children}</span></span>;
}
