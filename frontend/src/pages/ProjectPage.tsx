import { Link, useParams } from "react-router-dom";

import { useAppLayout } from "../components/appLayoutContext";
import { ArrowLeftIcon } from "../components/Icons";
import { SourceImagePanel } from "../components/SourceImagePanel";
import { useProjects } from "../hooks/useProjects";

export function ProjectPage() {
  const { projectId } = useParams();
  const { session } = useAppLayout();
  const projects = useProjects(session.access_token, session.user.id);
  const project = projects.data?.find((candidate) => candidate.id === projectId);

  return (
    <div className="page__container">
      <Link to="/" className="back-link">
        <ArrowLeftIcon size={16} />
        All projects
      </Link>

      {projects.isPending ? <p className="status status--pending" role="status">Loading project…</p> : null}
      {projects.isError ? (
        <div className="form-error" role="alert">
          <p>We could not load this project.</p>
          <button className="text-button" type="button" onClick={() => void projects.refetch()}>
            Try again
          </button>
        </div>
      ) : null}

      {projects.isSuccess && !project ? (
        <div className="page-heading">
          <div>
            <h1>Project not found</h1>
            <p className="page-heading__meta">It may have been deleted, or the link may be wrong.</p>
          </div>
        </div>
      ) : null}

      {project ? (
        <>
          <div className="page-heading">
            <h1>{project.name}</h1>
          </div>
          {/* Keyed by project so upload and generation state never leaks between projects. */}
          <SourceImagePanel
            key={project.id}
            accessToken={session.access_token}
            userId={session.user.id}
            projectId={project.id}
          />
        </>
      ) : null}
    </div>
  );
}
