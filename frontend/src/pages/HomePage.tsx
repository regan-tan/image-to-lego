import { BackendStatus } from "../components/BackendStatus";

export function HomePage() {
  return (
    <main className="shell">
      <section className="panel" aria-labelledby="project-title">
        <p className="eyebrow">University capstone</p>
        <h1 id="project-title">Image to LEGO</h1>
        <p className="summary">
          The project foundation is ready. Reconstruction and LEGO conversion workflows will be
          added in later milestones.
        </p>
        <BackendStatus />
      </section>
    </main>
  );
}

