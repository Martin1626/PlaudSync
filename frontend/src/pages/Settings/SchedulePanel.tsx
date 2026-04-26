import { useEffect, useMemo, useState } from "react";

import { ScheduleValidationError } from "@/api/client";
import { useSaveSchedule, useSchedule } from "@/api/hooks";
import type { Schedule } from "@/api/types";
import { useToasts } from "@/context/ToastsContext";
import { classNames } from "@/utils/format";

const DAYS: { code: number; label: string }[] = [
  { code: 1, label: "Po" },
  { code: 2, label: "Út" },
  { code: 3, label: "St" },
  { code: 4, label: "Čt" },
  { code: 5, label: "Pá" },
  { code: 6, label: "So" },
  { code: 7, label: "Ne" },
];

function isHHMM(value: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

export default function SchedulePanel() {
  const { data, isPending, error } = useSchedule();
  const save = useSaveSchedule();
  const { pushToast } = useToasts();

  const [draft, setDraft] = useState<Schedule | null>(null);
  const [serverErrors, setServerErrors] = useState<string[]>([]);

  useEffect(() => {
    if (data) setDraft(data);
  }, [data]);

  const localErrors = useMemo(() => {
    if (!draft) return [];
    const errs: string[] = [];
    if (draft.work_hours_interval_minutes < 1)
      errs.push("Interval pracovní doby musí být alespoň 1 minuta.");
    if (draft.off_hours_interval_minutes < 1)
      errs.push("Interval mimo pracovní dobu musí být alespoň 1 minuta.");
    if (!draft.work_days.length)
      errs.push("Vyber alespoň jeden pracovní den.");
    if (!isHHMM(draft.work_from)) errs.push("Začátek pracovní doby není ve formátu HH:MM.");
    if (!isHHMM(draft.work_to)) errs.push("Konec pracovní doby není ve formátu HH:MM.");
    if (
      isHHMM(draft.work_from) &&
      isHHMM(draft.work_to) &&
      draft.work_from >= draft.work_to
    ) {
      errs.push("Začátek pracovní doby musí být dříve než konec.");
    }
    return errs;
  }, [draft]);

  const dirty = useMemo(() => {
    if (!draft || !data) return false;
    return JSON.stringify(draft) !== JSON.stringify(data);
  }, [draft, data]);

  if (isPending && !data) {
    return (
      <section className="bg-white rounded-lg border border-gray-200 shadow-sm p-5">
        <p className="text-sm text-gray-500">Načítám plán synchronizace…</p>
      </section>
    );
  }

  if (error || !draft) {
    return (
      <section className="bg-white rounded-lg border border-red-200 shadow-sm p-5 text-sm text-red-800">
        Plán synchronizace se nepodařilo načíst.
      </section>
    );
  }

  const toggleDay = (code: number) => {
    setDraft((d) => {
      if (!d) return d;
      const has = d.work_days.includes(code);
      const next = has
        ? d.work_days.filter((x) => x !== code)
        : [...d.work_days, code].sort((a, b) => a - b);
      return { ...d, work_days: next };
    });
  };

  const onSave = () => {
    if (!draft || localErrors.length > 0) return;
    setServerErrors([]);
    save.mutate(draft, {
      onSuccess: () => {
        pushToast("success", "Plán synchronizace uložen");
      },
      onError: (err) => {
        if (err instanceof ScheduleValidationError) {
          setServerErrors(err.errors);
          pushToast("error", "Plán je neplatný — zkontroluj pole");
          return;
        }
        pushToast("error", "Uložení plánu selhalo");
      },
    });
  };

  const allErrors = [...localErrors, ...serverErrors];
  const canSave = dirty && localErrors.length === 0 && !save.isPending;

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-5 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-900">Plán synchronizace</h2>
        <p className="text-[13px] text-gray-500 mt-1">
          Jak často spouštět automatickou synchronizaci. Task Scheduler musí
          běžet alespoň tak často, jako nejkratší interval (typicky 15 min) —
          PlaudSync sám rozhodne, jestli daný tick proběhne.
        </p>
      </div>
      <div className="p-5 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Interval v pracovní době (minuty)
            </label>
            <input
              type="number"
              min={1}
              max={1440}
              value={draft.work_hours_interval_minutes}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  work_hours_interval_minutes: Number(e.target.value || 0),
                })
              }
              className="w-full px-3 py-2 rounded-md border border-gray-200 bg-white text-sm font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Interval mimo pracovní dobu (minuty)
            </label>
            <input
              type="number"
              min={1}
              max={1440}
              value={draft.off_hours_interval_minutes}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  off_hours_interval_minutes: Number(e.target.value || 0),
                })
              }
              className="w-full px-3 py-2 rounded-md border border-gray-200 bg-white text-sm font-mono"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">
            Pracovní dny
          </label>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((d) => {
              const active = draft.work_days.includes(d.code);
              return (
                <button
                  key={d.code}
                  type="button"
                  onClick={() => toggleDay(d.code)}
                  className={classNames(
                    "px-3 py-1.5 rounded-md text-sm font-medium border transition-colors",
                    active
                      ? "bg-blue-600 border-blue-600 text-white"
                      : "bg-white border-gray-200 text-gray-700 hover:bg-gray-50",
                  )}
                  aria-pressed={active}
                >
                  {d.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-5 max-w-md">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Začátek pracovní doby
            </label>
            <input
              type="time"
              value={draft.work_from}
              onChange={(e) => setDraft({ ...draft, work_from: e.target.value })}
              className="w-full px-3 py-2 rounded-md border border-gray-200 bg-white text-sm font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Konec pracovní doby
            </label>
            <input
              type="time"
              value={draft.work_to}
              onChange={(e) => setDraft({ ...draft, work_to: e.target.value })}
              className="w-full px-3 py-2 rounded-md border border-gray-200 bg-white text-sm font-mono"
            />
          </div>
        </div>

        {allErrors.length > 0 && (
          <ul className="text-[13px] text-red-700 bg-red-50 border border-red-200 rounded-md p-3 space-y-1 list-disc list-inside">
            {allErrors.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-3 pt-1">
          <button
            type="button"
            disabled={!canSave}
            onClick={onSave}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white shadow-sm disabled:opacity-60"
          >
            {save.isPending ? (
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
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                <path d="M17 21v-8H7v8M7 3v5h8" />
              </svg>
            )}
            Uložit plán
          </button>
          {dirty && (
            <button
              type="button"
              onClick={() => data && setDraft(data)}
              className="text-sm text-gray-500 hover:text-gray-800"
            >
              Zrušit změny
            </button>
          )}
          <span className="ml-auto text-[12px] text-gray-400">
            Pracovní doba: {draft.work_from}–{draft.work_to} • {draft.work_hours_interval_minutes}/{draft.off_hours_interval_minutes} min
          </span>
        </div>
      </div>
    </section>
  );
}
