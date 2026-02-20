/**
 * WellBridge brand logo — SVG icon + wordmark.
 *
 * Icon concept: a bridge arch with an EKG heartbeat line running across
 * the deck — the bridge connects patients to their health information,
 * the pulse signals the medical context.
 */

interface Props {
  /** Controls icon + text scale. */
  size?: "sm" | "md" | "lg" | "xl";
  /** Whether to render the "WellBridge" wordmark next to the icon. */
  showText?: boolean;
  className?: string;
}

const ICON_PX = { sm: 28, md: 36, lg: 48, xl: 64 } as const;
const TEXT_CLASS = {
  sm: "text-xl",
  md: "text-2xl",
  lg: "text-3xl",
  xl: "text-5xl",
} as const;

export default function WellbridgeLogo({
  size = "md",
  showText = true,
  className,
}: Props) {
  const px = ICON_PX[size];

  return (
    <div className={`flex items-center gap-2.5 ${className ?? ""}`}>
      {/* ── Icon ── */}
      <svg
        width={px}
        height={px}
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        {/* Arch */}
        <path
          d="M5 30 Q24 5 43 30"
          stroke="#2563eb"
          strokeWidth="4"
          strokeLinecap="round"
          fill="none"
        />

        {/* Left pillar */}
        <rect x="5" y="30" width="6" height="13" rx="1.5" fill="#2563eb" />

        {/* Right pillar */}
        <rect x="37" y="30" width="6" height="13" rx="1.5" fill="#2563eb" />

        {/* Bridge deck */}
        <rect x="5" y="30" width="38" height="4.5" rx="0.5" fill="#1d4ed8" />

        {/* EKG heartbeat line — sits on the deck, spike reaches into the arch */}
        <path
          d="M8 32.2 L17 32.2 L19.5 24 L22 40 L24 19 L26 40 L28.5 24 L31 32.2 L40 32.2"
          stroke="white"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </svg>

      {/* ── Wordmark ── */}
      {showText && (
        <span className={`font-bold text-brand-700 tracking-tight ${TEXT_CLASS[size]}`}>
          WellBridge
        </span>
      )}
    </div>
  );
}
