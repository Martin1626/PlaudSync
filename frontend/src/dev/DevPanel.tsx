import { useState } from "react";

import type { BannerData } from "@/components/Banner";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";
import { classNames } from "@/utils/format";

import { SCENARIOS, type ScenarioKey } from "./mockState";
import { useMockContext } from "./MockProvider";

export default function DevPanel() {
  if (!import.meta.env.DEV) return null;
  return <DevPanelImpl />;
}

function DevPanelImpl() {
  const ctx = useMockContext();
  const { pushBanner } = useBanners();
  const { pushToast } = useToasts();
  const [open, setOpen] = useState(true);

  if (!ctx) return null;

  const forceBanner = (kind: "token-expired" | "last-sync-failed") => {
    const banner: BannerData =
      kind === "token-expired"
        ? {
            id: "token-expired",
            variant: "error",
            title: "Token vypršel",
            message:
              "Zkopíruj znovu localStorage.tokenstr z app.plaud.ai do souboru .env.",
            actionLabel: "Otevřít Nastavení",
            actionTarget: "settings",
          }
        : {
            id: "last-sync-failed-forced",
            variant: "error",
            title: "Poslední synchronizace selhala",
            message: "Síť nedostupná při načítání seznamu nahrávek.",
            actionLabel: "Zobrazit log",
          };
    pushBanner(banner);
  };

  return (
    <div className="fixed bottom-4 left-4 z-40">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="px-2.5 py-1.5 rounded-md bg-gray-900 text-white text-[11px] font-mono shadow-md hover:bg-gray-800"
        >
          ▶ DEV
        </button>
      ) : (
        <div className="w-72 bg-gray-900 text-gray-100 rounded-lg shadow-md border border-gray-800 overflow-hidden font-mono text-[11px]">
          <div className="flex items-center justify-between px-3 py-2 bg-gray-950 border-b border-gray-800">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              <span className="font-semibold tracking-wider">DEV PANEL</span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-gray-400 hover:text-white"
              aria-label="Sbalit"
            >
              <svg
                viewBox="0 0 24 24"
                className="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
          </div>
          <div className="p-3 space-y-3">
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Scenario
              </div>
              <div className="grid grid-cols-2 gap-1">
                {(Object.entries(SCENARIOS) as [ScenarioKey, { label: string; desc: string }][]).map(
                  ([key, s]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => ctx.setScenario(key)}
                      className={classNames(
                        "px-2 py-1.5 rounded text-left leading-tight",
                        ctx.scenario === key
                          ? "bg-blue-600 text-white"
                          : "bg-gray-800 hover:bg-gray-700 text-gray-200",
                      )}
                      title={s.desc}
                    >
                      {s.label}
                    </button>
                  ),
                )}
              </div>
            </div>
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Toasts
              </div>
              <div className="grid grid-cols-2 gap-1">
                <button
                  onClick={() =>
                    pushToast(
                      "success",
                      "Synchronizace dokončena — 5 nových nahrávek",
                    )
                  }
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  success
                </button>
                <button
                  onClick={() =>
                    pushToast("error", "Synchronizaci se nepodařilo spustit")
                  }
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  error
                </button>
              </div>
            </div>
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Banners
              </div>
              <div className="grid grid-cols-2 gap-1">
                <button
                  onClick={() => forceBanner("token-expired")}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  token expired
                </button>
                <button
                  onClick={() => forceBanner("last-sync-failed")}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  sync failed
                </button>
              </div>
            </div>
            <div>
              <div className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">
                Overlay
              </div>
              <div className="grid grid-cols-2 gap-1">
                <button
                  onClick={() => ctx.setShowOverlay(true)}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  show
                </button>
                <button
                  onClick={() => ctx.setShowOverlay(false)}
                  className="px-2 py-1.5 rounded bg-gray-800 hover:bg-gray-700"
                >
                  hide
                </button>
              </div>
            </div>
            <div className="text-gray-500 text-[10px] pt-1 border-t border-gray-800">
              Dev only — stripped from production build via import.meta.env.DEV.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
