interface Props {
  visible: boolean;
  /** Dev-only "Skrýt" button. When omitted, no dismiss control rendered. */
  onClose?: () => void;
  /** Last error string (e.g. "ECONNREFUSED 127.0.0.1:8765"). */
  lastError?: string;
}

export default function ConnectionLostOverlay({
  visible,
  onClose,
  lastError,
}: Props) {
  if (!visible) return null;
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="conn-lost-title"
      className="fixed inset-0 z-50 bg-gray-900/40 backdrop-blur-sm flex items-center justify-center p-6"
    >
      <div className="bg-white rounded-lg shadow-md max-w-md w-full p-6 border border-gray-200">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-red-100 text-red-600 flex items-center justify-center flex-shrink-0">
            <svg
              viewBox="0 0 24 24"
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M2 12s4-8 10-8 10 8 10 8" />
              <path d="M2 2l20 20" />
            </svg>
          </div>
          <div className="flex-1">
            <h2
              id="conn-lost-title"
              className="text-base font-semibold text-gray-900"
            >
              Spojení s PlaudSync ztraceno
            </h2>
            <p className="text-sm text-gray-600 mt-1">
              Místní sync služba neodpovídá. Zavři toto okno a otevři ho znovu.
            </p>
            {lastError && (
              <p className="text-xs text-gray-500 mt-3 font-mono">
                3× pokus o spojení selhal — poslední chyba:{" "}
                <span className="text-gray-700">{lastError}</span>
              </p>
            )}
            {onClose && (
              <div className="mt-4 flex justify-end">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md"
                >
                  Skrýt (dev)
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
