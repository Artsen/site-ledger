# Site Ledger Knowledge Graph

Canonical snapshot: `main@6e17e08e641b48660a7ed7a13d9227b288fcafc6` (2026-09-03).

This is a generated human-readable projection of `graph.json`. Edit `graph.json`, then regenerate this file.

```mermaid
flowchart LR
    product["Product & Workspace"]
    truth_model["Truth Model"]
    site_identity["Site / Page / Resource Identity"]
    url_identity["URL Identity"]
    static_scan["Static Scan"]
    network_security["Crawler Network Security"]
    sources["Source Definitions & Current Inventory"]
    source_evidence["Immutable Source Evidence"]
    background_jobs["Durable Background Jobs"]
    job_followups["Required Follow-ups"]
    render["Rendered Evidence"]
    performance["Performance Evidence"]
    accessibility["Accessibility Evidence"]
    structured_content["Structured Content"]
    scan_projections["Scan Projections"]
    comparisons["Scan Comparisons"]
    findings["Findings"]
    site_intelligence["Site Intelligence"]
    collection_plans["Collection Plans"]
    categories["Page Categories & Rules"]
    website_graph["Website Graph"]
    frontend["Frontend Workspace"]
    persistence["Persistence"]
    testing["Invariant-focused Testing"]
    api["HTTP API"]
    product -->|organized_by| truth_model
    product -->|presented_by| frontend
    product -->|scoped_by| site_identity
    site_identity -->|depends_on| url_identity
    static_scan -->|records| site_identity
    static_scan -->|guarded_by| network_security
    sources -->|declares_candidates_for| site_identity
    sources -->|normalizes_with| url_identity
    static_scan -->|executed_by| background_jobs
    sources -->|refresh_executed_by| background_jobs
    render -->|executed_by| background_jobs
    performance -->|executed_by| background_jobs
    accessibility -->|executed_by| background_jobs
    structured_content -->|executed_by| background_jobs
    scan_projections -->|built_by| background_jobs
    comparisons -->|built_by| background_jobs
    findings -->|evaluated_by| background_jobs
    background_jobs -->|leases_and_fences_in| persistence
    background_jobs -->|terminalizes_into| job_followups
    static_scan -->|triggers| job_followups
    job_followups -->|enqueues| scan_projections
    job_followups -->|reconciles| categories
    scan_projections -->|derived_from| static_scan
    comparisons -->|pins| scan_projections
    website_graph -->|reads| static_scan
    structured_content -->|derives_from| static_scan
    findings -->|evaluates| static_scan
    findings -->|adjacent_to| scan_projections
    site_intelligence -->|summarizes| static_scan
    site_intelligence -->|summarizes| render
    site_intelligence -->|summarizes| performance
    site_intelligence -->|summarizes| accessibility
    site_intelligence -->|summarizes| structured_content
    site_intelligence -->|summarizes| comparisons
    site_intelligence -->|summarizes| sources
    site_intelligence -->|surfaces| findings
    collection_plans -->|freezes_active_page_universe| site_identity
    collection_plans -->|targets_missing_current| render
    collection_plans -->|targets_missing_current| performance
    collection_plans -->|targets_missing_current| accessibility
    collection_plans -->|targets_missing_current| structured_content
    frontend -->|renders| site_intelligence
    frontend -->|renders| findings
    frontend -->|renders| collection_plans
    frontend -->|renders| website_graph
    api -->|exposes| site_intelligence
    api -->|exposes| findings
    api -->|exposes| collection_plans
    api -->|exposes| static_scan
    testing -->|stress_tests| background_jobs
    testing -->|stress_tests| network_security
    testing -->|verifies| findings
    testing -->|verifies| collection_plans
    testing -->|verifies| scan_projections
    testing -->|verifies| comparisons
    sources -->|records| source_evidence
    source_evidence -->|normalizes_with| url_identity
    findings -->|evaluates| source_evidence
    testing -->|verifies| source_evidence
```
