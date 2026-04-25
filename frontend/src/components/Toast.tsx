import { classNames } from "@/utils/format";

export type ToastVariant = "success" | "error";

export interface ToastData {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface Props {
  toast: ToastData;
  onDismiss: (id: number) => void;
}

export default function Toast({ toast, onDismiss }: Props) {
  const isSuccess = toast.variant === "success";
  return (
    <div
      role="status"
      className="animate-ps-toast-in flex items-center gap-3 pl-3 pr-2 py-2.5 rounded-lg shadow-md border min-w-[280px] max-w-sm cursor-pointer bg-white border-gray-200"
      onClick={() => onDismiss(toast.id)}
    >
      <div
        className={classNames(
          "w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0",
          isSuccess ? "bg-green-100 text-green-600" : "bg-red-100 text-red-600",
        )}
      >
        {isSuccess ? (
          <svg
            viewBox="0 0 24 24"
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M5 12l5 5L20 7" />
          </svg>
        ) : (
          <svg
            viewBox="0 0 24 24"
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        )}
      </div>
      <div className="text-[13px] text-gray-900 flex-1">{toast.message}</div>
      <button
        className="text-gray-400 hover:text-gray-600 p-1"
        aria-label="Zavřít"
        onClick={(e) => {
          e.stopPropagation();
          onDismiss(toast.id);
        }}
      >
        <svg
          viewBox="0 0 24 24"
          className="w-3.5 h-3.5"
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
