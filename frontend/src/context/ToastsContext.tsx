import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import type { ToastData, ToastVariant } from "@/components/Toast";

interface ToastsContextValue {
  toasts: ToastData[];
  pushToast: (variant: ToastVariant, message: string) => void;
  dismissToast: (id: number) => void;
}

const ToastsContext = createContext<ToastsContextValue | null>(null);

const AUTO_DISMISS_MS = 4000;

export function ToastsProvider({ children }: PropsWithChildren) {
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const idRef = useRef(0);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (variant: ToastVariant, message: string) => {
      idRef.current += 1;
      const id = idRef.current;
      setToasts((prev) => [...prev, { id, variant, message }]);
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, AUTO_DISMISS_MS);
    },
    [],
  );

  const value = useMemo(
    () => ({ toasts, pushToast, dismissToast }),
    [toasts, pushToast, dismissToast],
  );

  return (
    <ToastsContext.Provider value={value}>{children}</ToastsContext.Provider>
  );
}

export function useToasts(): ToastsContextValue {
  const ctx = useContext(ToastsContext);
  if (!ctx) throw new Error("useToasts must be used within ToastsProvider");
  return ctx;
}
