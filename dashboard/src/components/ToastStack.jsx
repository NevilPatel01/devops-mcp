import { useCallback, useEffect, useState } from "react";

const TOAST_TTL_MS = 6000;

export function useToasts() {
  const [toasts, setToasts] = useState([]);

  const push = useCallback((toast) => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev, { id, ...toast }]);
    return id;
  }, []);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    if (!toasts.length) return undefined;
    const timers = toasts.map((t) =>
      setTimeout(() => dismiss(t.id), TOAST_TTL_MS)
    );
    return () => timers.forEach(clearTimeout);
  }, [toasts, dismiss]);

  return { toasts, push, dismiss };
}

const toneStyles = {
  info: "border-sky-700/60 bg-sky-950/90 text-sky-100",
  success: "border-emerald-700/60 bg-emerald-950/90 text-emerald-100",
  warning: "border-amber-700/60 bg-amber-950/90 text-amber-100",
};

export default function ToastStack({ toasts, onDismiss }) {
  if (!toasts.length) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex max-w-sm flex-col gap-2"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto rounded-lg border px-4 py-3 shadow-lg backdrop-blur transition-all duration-300 ${
            toneStyles[t.tone] || toneStyles.info
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              {t.title && <p className="text-sm font-medium">{t.title}</p>}
              {t.body && <p className="mt-0.5 text-xs opacity-90">{t.body}</p>}
            </div>
            <button
              type="button"
              onClick={() => onDismiss(t.id)}
              className="shrink-0 text-xs opacity-60 hover:opacity-100"
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
