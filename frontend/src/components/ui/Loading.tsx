export function LoadingBlock({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="animate-pulse rounded-md border border-stone-200 bg-white p-4 text-sm text-stone-500" aria-busy="true">
      {label}
    </div>
  );
}
