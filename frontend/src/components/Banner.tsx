import { classNames } from "@/utils/format";

export type BannerVariant = "error" | "warning" | "info";

export interface BannerData {
  id: string;
  variant: BannerVariant;
  title: string;
  message: string;
  actionLabel?: string;
  /** Route key, e.g. "settings". When set, action navigates there. */
  actionTarget?: "settings";
}

interface Props {
  banner: BannerData;
  onDismiss: (id: string) => void;
  onAction: (banner: BannerData) => void;
}

const VARIANT: Record<
  BannerVariant,
  {
    bg: string;
    border: string;
    iconColor: string;
    titleColor: string;
    bodyColor: string;
  }
> = {
  error: {
    bg: "bg-red-50",
    border: "border-red-200",
    iconColor: "text-red-600",
    titleColor: "text-red-900",
    bodyColor: "text-red-800",
  },
  warning: {
    bg: "bg-amber-50",
    border: "border-amber-200",
    iconColor: "text-amber-600",
    titleColor: "text-amber-900",
    bodyColor: "text-amber-800",
  },
  info: {
    bg: "bg-blue-50",
    border: "border-blue-200",
    iconColor: "text-blue-600",
    titleColor: "text-blue-900",
    bodyColor: "text-blue-800",
  },
};

function VariantIcon({
  variant,
  className,
}: {
  variant: BannerVariant;
  className: string;
}) {
  const common = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };
  if (variant === "error") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v4M12 16h.01" />
      </svg>
    );
  }
  if (variant === "warning") {
    return (
      <svg {...common}>
        <path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z" />
        <path d="M12 9v4M12 17h.01" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}

export default function Banner({ banner, onDismiss, onAction }: Props) {
  const c = VARIANT[banner.variant];
  return (
    <div
      className={classNames(
        "flex gap-3 items-start px-4 py-3 border",
        c.bg,
        c.border,
      )}
    >
      <VariantIcon
        variant={banner.variant}
        className={classNames("w-5 h-5 mt-0.5 flex-shrink-0", c.iconColor)}
      />
      <div className="flex-1 min-w-0">
        <div className={classNames("text-[13px] font-semibold", c.titleColor)}>
          {banner.title}
        </div>
        <div className={classNames("text-[13px] mt-0.5", c.bodyColor)}>
          {banner.message}
        </div>
      </div>
      {banner.actionLabel && (
        <button
          type="button"
          onClick={() => onAction(banner)}
          className={classNames(
            "text-[13px] font-medium underline-offset-2 hover:underline",
            c.titleColor,
          )}
        >
          {banner.actionLabel}
        </button>
      )}
      <button
        type="button"
        onClick={() => onDismiss(banner.id)}
        className={classNames("p-1 rounded hover:bg-black/5", c.bodyColor)}
        aria-label="Zavřít"
      >
        <svg
          viewBox="0 0 24 24"
          className="w-4 h-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
