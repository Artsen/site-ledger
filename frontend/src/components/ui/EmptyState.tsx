export function EmptyState({ title, message, action }: { title: string; message: string; action?: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-stone-300 bg-white px-4 py-8 text-center">
      <div className="text-sm font-medium text-stone-900">{title}</div>
      <div className="mt-1 text-sm text-stone-600">{message}</div>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
