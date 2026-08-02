import type { IconName } from "./Icon";

export type StatusTone = "verified" | "warning" | "failed" | "neutral" | "info";

export const toneIcons: Record<StatusTone, IconName> = {
  verified: "check",
  warning: "alert",
  failed: "close",
  neutral: "layers",
  info: "link",
};

export function statusTone(status: string): StatusTone {
  if (["valid", "verified_compressed", "verified_repaired", "passed", "complete"].includes(status)) return "verified";
  if (["failed", "invalid", "full_fallback"].includes(status)) return "failed";
  if (["incompressible", "expand_budget", "restore_spans", "prepared_only", "not_run"].includes(status)) return "warning";
  return "neutral";
}
