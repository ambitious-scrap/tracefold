import type { ReactElement, SVGProps } from "react";

export type IconName =
  | "compress"
  | "proof"
  | "recovery"
  | "benchmarks"
  | "architecture"
  | "search"
  | "copy"
  | "check"
  | "alert"
  | "arrow"
  | "external"
  | "menu"
  | "close"
  | "keyboard"
  | "layers"
  | "link"
  | "lock"
  | "play"
  | "chevron";

export function Icon({ name, size = 18, ...props }: SVGProps<SVGSVGElement> & { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  const shapes: Record<IconName, ReactElement> = {
    compress: <><path d="M4 7h6M14 7h6M4 17h6M14 17h6" /><path d="M10 4 7 7l3 3M14 14l3 3-3 3" /><path d="M7 7h10M7 17h10" /></>,
    proof: <><path d="m12 3 7 3v5c0 4.6-2.9 8-7 10-4.1-2-7-5.4-7-10V6l7-3Z" /><path d="m8.5 12 2.2 2.2 4.8-5" /></>,
    recovery: <><path d="M4 12a8 8 0 1 0 2.3-5.7" /><path d="M4 4v5h5" /><path d="M12 8v4l2.5 2" /></>,
    benchmarks: <><path d="M4 19V5M4 19h17" /><path d="m7 15 3-4 3 2 5-7" /><path d="M18 6h2v2" /></>,
    architecture: <><circle cx="12" cy="5" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="18" r="2" /><path d="M12 7v5M12 12 5 16M12 12l7 4" /></>,
    search: <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.5 4.5" /></>,
    copy: <><rect x="8" y="8" width="11" height="12" rx="1.5" /><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v10A1.5 1.5 0 0 0 5.5 17H8" /></>,
    check: <><path d="m5 12 4 4L19 6" /></>,
    alert: <><path d="M12 3 2.8 20h18.4L12 3Z" /><path d="M12 9v5M12 17h.01" /></>,
    arrow: <><path d="M5 12h13M13 6l6 6-6 6" /></>,
    external: <><path d="M14 5h5v5M19 5l-8 8" /><path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    keyboard: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M7 14h10" /></>,
    layers: <><path d="m12 3 8 4-8 4-8-4 8-4Z" /><path d="m4 12 8 4 8-4M4 17l8 4 8-4" /></>,
    link: <><path d="M10 13a5 5 0 0 0 7.1.1l1.4-1.4a5 5 0 0 0-7.1-7.1L10.6 5.4" /><path d="M14 11a5 5 0 0 0-7.1-.1l-1.4 1.4a5 5 0 0 0 7.1 7.1l.8-.8" /></>,
    lock: <><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v2" /></>,
    play: <path d="m9 6 9 6-9 6V6Z" />,
    chevron: <path d="m9 18 6-6-6-6" />,
  };
  return <svg {...common} {...props}>{shapes[name]}</svg>;
}
