import type { RecordingStatus } from "@/api/types";

interface Props {
  status: RecordingStatus;
}

export default function StatusIcon({ status }: Props) {
  if (status === "downloaded") {
    return (
      <span
        className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-green-100 text-green-600"
        title="Staženo"
      >
        <svg
          viewBox="0 0 24 24"
          className="w-3 h-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M5 12l5 5L20 7" />
        </svg>
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-100 text-red-600"
        title="Selhalo"
      >
        <svg
          viewBox="0 0 24 24"
          className="w-3 h-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gray-100 text-gray-500"
      title="Přeskočeno"
    >
      <svg
        viewBox="0 0 24 24"
        className="w-3 h-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 9 9 9 9 0 0 1-9 9" />
        <path d="M3 12v4h4" />
      </svg>
    </span>
  );
}
