import { useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  useConfirmSample,
  useExcludeSample,
  useRenameSample,
} from "@/api/hooks";
import type { SpeakerSample } from "@/api/types";
import { useToasts } from "@/context/ToastsContext";

interface Props {
  sample: SpeakerSample;
  persons: string[];
}

const BTN =
  "px-3 py-1.5 text-sm font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed";

export default function SampleRow({ sample, persons }: Props) {
  const [name, setName] = useState("");
  const { pushToast } = useToasts();
  const confirm = useConfirmSample();
  const exclude = useExcludeSample();
  const rename = useRenameSample();

  const queued = sample.queued_name !== null;
  const busy =
    queued || confirm.isPending || exclude.isPending || rename.isPending;
  const trimmed = name.trim();
  const listId = `persons-${sample.id}`;

  const onError = () => pushToast("error", "Akci se nepodařilo provést.");

  const submitRename = () => {
    if (!trimmed) return;
    rename.mutate(
      { id: sample.id, name: trimmed },
      {
        onSuccess: () => setName(""),
        onError: (err) => {
          if (err instanceof ApiHttpError && err.status === 409) {
            pushToast("error", "Přejmenování už čeká na synchronizaci.");
          } else if (err instanceof ApiHttpError && err.status === 422) {
            pushToast("error", "Neplatné jméno.");
          } else {
            onError();
          }
        },
      },
    );
  };

  return (
    <li className="px-4 py-3 flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="font-medium text-gray-900">{sample.person}</span>
        <span className="text-sm text-gray-600">{sample.recording_title}</span>
        <span className="text-sm text-gray-500">{sample.recording_date}</span>
        {sample.consistency !== null && (
          <span className="text-sm text-gray-500 tabular-nums">
            {sample.consistency.toFixed(2).replace(".", ",")}
          </span>
        )}
      </div>

      {sample.has_clip ? (
        <audio
          controls
          preload="none"
          src={`/api/speakers/${sample.id}/clip`}
          className="h-9 max-w-md"
        />
      ) : (
        <span className="text-sm text-gray-500">Audio není k dispozici</span>
      )}

      {queued && (
        <span className="text-sm text-amber-700">
          Čeká na synchronizaci → {sample.queued_name}
        </span>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={BTN}
          disabled={busy}
          onClick={() => confirm.mutate(sample.id, { onError })}
        >
          Potvrdit
        </button>
        <button
          type="button"
          className={BTN}
          disabled={busy}
          onClick={() => exclude.mutate(sample.id, { onError })}
        >
          Vyřadit
        </button>
        <input
          list={listId}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy) submitRename();
          }}
          disabled={busy}
          aria-label="Nové jméno"
          className="px-2 py-1.5 text-sm border border-gray-300 rounded-md disabled:opacity-50"
        />
        <datalist id={listId}>
          {persons.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
        <button
          type="button"
          className={BTN}
          disabled={busy || !trimmed}
          onClick={submitRename}
        >
          Přejmenovat
        </button>
      </div>
    </li>
  );
}
