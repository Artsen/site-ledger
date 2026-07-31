export function classificationLabel(value: string | null | undefined) {
  return value?.trim() || "Not specified";
}
