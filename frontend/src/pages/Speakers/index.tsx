import { useState } from "react";

import { useSpeakersQuery } from "@/api/hooks";
import type { SpeakersFilter } from "@/api/types";
import { classNames } from "@/utils/format";

import SampleRow from "./SampleRow";

const OPTIONS: Array<{ value: SpeakersFilter; label: string }> = [
  { value: "flagged", label: "Ke kontrole" },
  { value: "all", label: "Všechny vzorky" },
];

export default function Speakers() {
  const [filter, setFilter] = useState<SpeakersFilter>("flagged");
  const { data, isPending } = useSpeakersQuery(filter);

  return (
    <div className="flex flex-col gap-4">
      <div className="inline-flex self-start rounded-md border border-gray-200 bg-white p-0.5">
        {OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => setFilter(o.value)}
            className={classNames(
              "px-3 py-1.5 text-sm font-medium rounded",
              filter === o.value
                ? "bg-gray-100 text-gray-900"
                : "text-gray-600 hover:text-gray-900",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>

      {isPending && !data ? (
        <p className="text-sm text-gray-500">Načítám…</p>
      ) : !data || data.samples.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 text-center">Nic ke kontrole.</p>
      ) : (
        <ul className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-200">
          {data.samples.map((s) => (
            <SampleRow key={s.id} sample={s} persons={data.persons} />
          ))}
        </ul>
      )}
    </div>
  );
}
