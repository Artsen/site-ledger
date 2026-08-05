type SiteLedgerMarkProps = {
  className?: string;
};

export function SiteLedgerMark({ className }: SiteLedgerMarkProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M5.5 3.5h13v17h-13zM9 3.5v17" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 8h4M12 12h4M12 16h4" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
      <circle cx="7.25" cy="8" fill="currentColor" r="0.9" />
      <circle cx="7.25" cy="12" fill="currentColor" r="0.9" />
      <circle cx="7.25" cy="16" fill="currentColor" r="0.9" />
    </svg>
  );
}
