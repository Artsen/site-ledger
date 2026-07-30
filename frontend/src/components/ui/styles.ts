export function inputClass(hasError = false) {
  return `w-full rounded-md border bg-white px-3 py-2 text-sm text-stone-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-1 ${
    hasError ? "border-red-400" : "border-stone-300"
  }`;
}
