import type { ArtifactSize, ReductionMetric } from "../contracts/tracefold";
import { displayCount, formatReduction, reductionLabel } from "../contracts/tracefold";
import { StatusPill } from "./StatusPill";

export function MetricStrip({
  original,
  raw,
  final,
  requested,
  rawReduction,
  finalReduction,
}: {
  original: ArtifactSize;
  raw: ArtifactSize;
  final: ArtifactSize;
  requested: ReductionMetric;
  rawReduction: ReductionMetric;
  finalReduction: ReductionMetric;
}) {
  return (
    <section className="metric-strip" aria-label="Compression result metrics">
      <Metric label="Original size" value={formatPrimarySize(original)} detail={sizeDetail(original)} />
      <Metric label="Raw artifact size" value={formatPrimarySize(raw)} detail={sizeDetail(raw)} tone="neutral" />
      <Metric label="Final artifact size" value={formatPrimarySize(final)} detail={sizeDetail(final)} tone="verified" />
      <Metric label="Requested reduction" value={formatReduction(requested)} detail={reductionLabel(requested)} />
      <Metric label="Raw reduction" value={formatReduction(rawReduction)} detail={reductionLabel(rawReduction)} />
      <Metric label="Final reduction" value={formatReduction(finalReduction)} detail={reductionLabel(finalReduction)} tone="verified" />
    </section>
  );
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "verified" | "neutral" }) {
  return <div className="metric-cell"><span className="metric-label">{label}</span><strong className="metric-value">{value}</strong><span className="metric-detail">{tone === "verified" ? <StatusPill tone="verified">verified</StatusPill> : null}{detail}</span></div>;
}

function formatPrimarySize(size: ArtifactSize): string {
  const count = size.tokens;
  if (count && count.source !== "fixture_bytes" && count.value !== null) return `${displayCount(count)} tok`;
  return formatBytes(size.bytes);
}

function sizeDetail(size: ArtifactSize): string {
  const count = size.tokens;
  if (!count || count.value === null || count.source === "fixture_bytes") return `${formatBytes(size.bytes)} · structural byte count`;
  return `${formatBytes(size.bytes)} · ${count.counterIdentity}`;
}

function formatBytes(bytes: number | null): string {
  return bytes === null ? "bytes unavailable" : `${bytes.toLocaleString("en-US")} bytes`;
}
