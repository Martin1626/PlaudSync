import { Outlet } from "react-router-dom";

import { useStateQuery } from "@/api/hooks";
import type { SyncState } from "@/api/types";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";
import DevPanel from "@/dev/DevPanel";
import { useMockContext } from "@/dev/MockProvider";

import BannerStack from "./BannerStack";
import ConnectionLostOverlay from "./ConnectionLostOverlay";
import Header from "./Header";
import ToastContainer from "./ToastContainer";
import { useConnectionLost } from "./useConnectionLost";

const IDLE_SYNC: SyncState = {
  status: "idle",
  trigger: null,
  started_at: null,
  last_run_at: null,
  last_run_outcome: null,
  last_run_exit_code: null,
  last_error_summary: null,
  progress: null,
};

export default function AppShell() {
  const { data } = useStateQuery();
  const { banners, dismissBanner } = useBanners();
  const { toasts, pushToast, dismissToast } = useToasts();
  const conn = useConnectionLost();
  const mockCtx = useMockContext();
  const overlayVisible = (mockCtx?.showOverlay ?? false) || conn.visible;

  const sync = data?.sync ?? IDLE_SYNC;

  const onBannerAction = (banner: { id: string; actionTarget?: "settings" }) => {
    if (banner.actionTarget === "settings") {
      window.location.assign("/settings");
      return;
    }
    if (banner.id === "last-sync-failed" || banner.id === "last-sync-partial") {
      // Dashboard Gap 4 default C: point user to log file path. No project / path
      // interpolation per D11.
      pushToast(
        "success",
        "Logy najdeš v plaudsync.log v adresáři projektu.",
      );
      return;
    }
    if (banner.id === "sync-spawn-failed") {
      pushToast("success", "Logy najdeš v plaudsync.log v adresáři projektu.");
      return;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Header sync={sync} />
      <BannerStack
        banners={banners}
        onDismiss={dismissBanner}
        onAction={onBannerAction}
      />
      <main className="flex-1">
        <div className="max-w-6xl mx-auto px-6 py-6">
          <Outlet />
        </div>
      </main>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <ConnectionLostOverlay
        visible={overlayVisible}
        {...(conn.lastError !== undefined && { lastError: conn.lastError })}
        {...(mockCtx ? { onClose: () => mockCtx.setShowOverlay(false) } : {})}
      />
      <DevPanel />
    </div>
  );
}
