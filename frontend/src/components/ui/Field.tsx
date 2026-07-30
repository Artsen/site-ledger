import { ReactNode } from "react";

export function Field({ id, label, helper, error, children }: { id: string; label: string; helper?: ReactNode; error?: string | null; children: ReactNode }) {
  const helperId = `${id}-helper`;
  const errorId = `${id}-error`;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-stone-900">
        {label}
      </label>
      {children}
      {helper ? (
        <div id={helperId} className="mt-1 text-xs leading-5 text-stone-600">
          {helper}
        </div>
      ) : null}
      {error ? (
        <div id={errorId} className="mt-1 text-sm text-red-700">
          {error}
        </div>
      ) : null}
    </div>
  );
}
