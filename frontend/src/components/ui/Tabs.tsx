export type TabItem = {
  id: string;
  label: string;
  count?: number;
};

export function Tabs({ tabs, active, onChange }: { tabs: TabItem[]; active: string; onChange: (tab: string) => void }) {
  return (
    <div role="tablist" aria-label="Page sections" className="flex gap-1 border-b border-stone-200">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2 ${
            active === tab.id ? "border-neutral-900 font-medium text-stone-950" : "border-transparent text-stone-600 hover:text-stone-950"
          }`}
        >
          {tab.label}
          {tab.count != null ? <span className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-700">{tab.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
