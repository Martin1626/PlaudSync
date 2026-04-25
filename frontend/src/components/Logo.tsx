export default function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="relative w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center shadow-sm">
        <svg
          viewBox="0 0 24 24"
          className="w-4 h-4 text-white"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
          <path d="M21 4v4h-4" />
          <path d="M21 12a9 9 0 0 1-15.5 6.3L3 16" />
          <path d="M3 20v-4h4" />
        </svg>
      </div>
      <span className="font-semibold tracking-tight text-gray-900">PlaudSync</span>
    </div>
  );
}
