/**
 * Placeholder landing page. The real product surface is the Explore map
 * (app/explore/ — Phase 3): full-height MapLibre map, profile controls
 * on top, results drawer, comparison tray. Layout spec:
 * context/ui-context.md §"Layout Patterns".
 */
export default function Home() {
  return (
    <main
      style={{
        display: "grid",
        placeItems: "center",
        minHeight: "100vh",
        padding: "2rem",
      }}
    >
      <div
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border-default)",
          borderRadius: "0.5rem",
          padding: "2rem",
          maxWidth: "34rem",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>RetailScout</h1>
        <p style={{ color: "var(--text-muted)", marginTop: "0.75rem" }}>
          Location intelligence for the City of Melbourne. Scaffold is up;
          the Explore map arrives in Phase 3 once the scoring pipeline
          (Phases 1–2) populates the analytics tables.
        </p>
        <p style={{ color: "var(--text-muted)", marginTop: "0.75rem", fontSize: "0.875rem" }}>
          Data: City of Melbourne Open Data. Scores are decision-support
          estimates, not predictions of business success.
        </p>
      </div>
    </main>
  );
}
