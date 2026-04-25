import { useEffect } from "react";

import { useVerifyAuth } from "@/api/hooks";
import type { AuthVerifyResponse } from "@/api/types";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";

const PLACEHOLDER_MASK = "•".repeat(20);

export default function ConnectionPanel() {
  const verify = useVerifyAuth();
  const { pushToast } = useToasts();
  const { pushBanner, dismissBanner } = useBanners();

  // Settings v0.1 D2 + Gap 2 Option A: implicit verify on mount populates mask.
  useEffect(() => {
    verify.mutate(undefined, {
      onSuccess: (resp) => handleVerifyResult(resp, /*surfaceToast*/ false),
      // Network errors on mount are silent — not actionable until user clicks.
    });
    // Mount-only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleVerifyResult(resp: AuthVerifyResponse, surfaceToast: boolean) {
    if (resp.ok) {
      if (surfaceToast) pushToast("success", "Token ověřen");
      // Auth recovered — remove any token-related banners.
      dismissBanner("token-expired");
      dismissBanner("token-missing");
      return;
    }
    // ok=false — branch on reason.
    if (resp.reason === "PlaudTokenExpired") {
      pushBanner({
        id: "token-expired",
        variant: "error",
        title: "Token vypršel",
        message:
          "Zkopíruj znovu localStorage.tokenstr z app.plaud.ai do souboru .env.",
      });
    } else if (resp.reason === "PlaudTokenMissing") {
      pushBanner({
        id: "token-missing",
        variant: "error",
        title: "Token chybí",
        message: resp.message ?? "PLAUD_API_TOKEN není nastaven v .env.",
      });
    }
    if (surfaceToast) pushToast("error", "Ověření tokenu selhalo");
  }

  const onClick = () => {
    verify.mutate(undefined, {
      onSuccess: (resp) => handleVerifyResult(resp, true),
      onError: () => {
        pushToast("error", "Ověření tokenu selhalo — zkontroluj síť");
      },
    });
  };

  const masked = verify.data?.masked_token ?? PLACEHOLDER_MASK;

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-5 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-900">Připojení k Plaud</h2>
        <p className="text-[13px] text-gray-500 mt-1">
          Token se načítá ze souboru{" "}
          <span className="font-mono text-gray-700">.env</span> (
          <span className="font-mono">PLAUD_API_TOKEN</span>). Z UI se needituje.
        </p>
      </div>
      <div className="p-5 space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Plaud API token
          </label>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex-1 min-w-[260px] flex items-center gap-2 px-3 py-2 rounded-md bg-gray-50 border border-gray-200 font-mono text-[13px] text-gray-700">
              <svg
                viewBox="0 0 24 24"
                className="w-4 h-4 text-gray-400"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <span className="truncate">{masked}</span>
              <span className="ml-auto text-[11px] text-gray-400 px-1.5 py-0.5 rounded bg-white border border-gray-200">
                z .env
              </span>
            </div>
            <button
              type="button"
              disabled={verify.isPending}
              onClick={onClick}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 disabled:opacity-60"
            >
              {verify.isPending ? (
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4 animate-spin"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M21 12a9 9 0 1 1-6.2-8.55" />
                </svg>
              ) : (
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
                  <path d="M5 12l5 5L20 7" />
                </svg>
              )}
              Otestovat připojení
            </button>
          </div>
        </div>
        <div className="text-[13px] text-gray-500 leading-relaxed bg-gray-50 border border-gray-200 rounded-md p-3">
          <span className="font-medium text-gray-700">Aktualizace tokenu:</span>{" "}
          otevři <span className="font-mono">app.plaud.ai</span> v prohlížeči, v
          DevTools spusť <span className="font-mono">localStorage.tokenstr</span>{" "}
          a hodnotu vlož do souboru <span className="font-mono">.env</span> pod
          klíč <span className="font-mono">PLAUD_API_TOKEN</span>.
        </div>
      </div>
    </section>
  );
}
