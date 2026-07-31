export const groupOptions = [
  { value: "marketing", label: "Marketing" },
  { value: "customer_education", label: "Customer Education" },
  { value: "rs", label: "RS" },
  { value: "other", label: "Other" }
];

export const platformOptions = [
  { value: "wordpress_root", label: "WordPress Root" },
  { value: "wordpress_learn", label: "WordPress Learn" },
  { value: "rs_managed", label: "RS Managed" },
  { value: "other", label: "Other" }
];

export const ownershipOptions = [
  { value: "web_team", label: "Web Team" },
  { value: "customer_education", label: "Customer Education" },
  { value: "rs", label: "RS" },
  { value: "shared", label: "Shared" },
  { value: "unknown", label: "Unknown" }
];

export function classificationLabel(options: Array<{ value: string; label: string }>, value: string | null | undefined) {
  return options.find((option) => option.value === value)?.label ?? "Unknown";
}
