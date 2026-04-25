import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import type { BannerData } from "@/components/Banner";
import type { SyncState } from "@/api/types";

interface BannersContextValue {
  banners: BannerData[];
  pushBanner: (banner: BannerData) => void;
  dismissBanner: (id: string) => void;
  /**
   * Sync the auto-derived banners (last-sync-failed / last-sync-partial) from
   * a fresh SyncState snapshot. Idempotent — callers can invoke on every
   * useStateQuery success without spawning duplicates.
   */
  syncFromState: (sync: SyncState) => void;
}

const BannersContext = createContext<BannersContextValue | null>(null);

const AUTO_BANNER_IDS = ["last-sync-failed", "last-sync-partial"] as const;

function deriveBannerForState(sync: SyncState): BannerData | null {
  if (sync.last_run_outcome === "failed") {
    return {
      id: "last-sync-failed",
      variant: "error",
      title: "Poslední synchronizace selhala",
      message: sync.last_error_summary ?? "Synchronizace nedoběhla.",
      actionLabel: "Zobrazit log",
    };
  }
  if (sync.last_run_outcome === "partial_failure") {
    return {
      id: "last-sync-partial",
      variant: "warning",
      title: "Poslední synchronizace měla chyby",
      message:
        sync.last_error_summary ?? "Některé nahrávky se nepodařilo stáhnout.",
      actionLabel: "Zobrazit log",
    };
  }
  return null;
}

export function BannersProvider({ children }: PropsWithChildren) {
  const [banners, setBanners] = useState<BannerData[]>([]);
  const dismissedRef = useRef<Set<string>>(new Set());

  const pushBanner = useCallback((banner: BannerData) => {
    setBanners((prev) =>
      prev.find((b) => b.id === banner.id) ? prev : [...prev, banner],
    );
  }, []);

  const dismissBanner = useCallback((id: string) => {
    dismissedRef.current.add(id);
    setBanners((prev) => prev.filter((b) => b.id !== id));
  }, []);

  const syncFromState = useCallback((sync: SyncState) => {
    const derived = deriveBannerForState(sync);
    setBanners((prev) => {
      // Remove any auto-derived banners that no longer apply (e.g. last_run_outcome flipped success).
      const kept = prev.filter(
        (b) => !AUTO_BANNER_IDS.includes(b.id as (typeof AUTO_BANNER_IDS)[number]),
      );
      if (!derived) return kept;
      if (dismissedRef.current.has(derived.id)) return kept;
      // Only append if not already present (re-render with same outcome).
      if (kept.find((b) => b.id === derived.id)) return kept;
      return [...kept, derived];
    });
  }, []);

  const value = useMemo(
    () => ({ banners, pushBanner, dismissBanner, syncFromState }),
    [banners, pushBanner, dismissBanner, syncFromState],
  );

  return (
    <BannersContext.Provider value={value}>
      {children}
    </BannersContext.Provider>
  );
}

export function useBanners(): BannersContextValue {
  const ctx = useContext(BannersContext);
  if (!ctx) throw new Error("useBanners must be used within BannersProvider");
  return ctx;
}
