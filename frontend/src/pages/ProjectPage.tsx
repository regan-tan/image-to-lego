import { Link, useParams } from "react-router-dom";

import { useAppLayout } from "../components/appLayoutContext";
import { BrickProgress } from "../components/BrickProgress";
import { ArrowLeftIcon } from "../components/Icons";
import { ProjectPreview } from "../components/ProjectPreview";
import { ProjectStatusPanel } from "../components/ProjectStatusPanel";
import { StatusBadge } from "../components/StatusBadge";
import { isNotFound, useProject } from "../hooks/useProjects";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const { session } = useAppLayout();
  const project = useProject(session.access_token, session.user.id, projectId);

  return (
    <div className="page__container">
      <Link to="/" className="back-link">
        <ArrowLeftIcon size={16} />
        All projects
      </Link>

      {project.isPending ? <p className="status status--pending" role="status">Loading project…</p> : null}

      {!project.data && isNotFound(project.error) ? (
        <div className="page-heading">
          <div>
            <h1>Project not found</h1>
            <p className="page-heading__meta">It may have been deleted, or the link may be wrong.</p>
          </div>
        </div>
      ) : null}

      {!project.data && project.isError && !isNotFound(project.error) ? (
        <div className="form-error" role="alert">
          <p>We could not load this project.</p>
          <button className="text-button" type="button" onClick={() => void project.refetch()}>
            Try again
          </button>
        </div>
      ) : null}

      {project.data ? (
        <>
          <div className="page-heading">
            <div className="page-heading__title-row">
              <h1>{project.data.name}</h1>
              <StatusBadge status={project.data.status} />
            </div>
          </div>
          <BrickProgress status={project.data.status} />
          <div className="project-layout">
            <ProjectPreview
              key={project.data.id}
              project={project.data}
              accessToken={session.access_token}
              userId={session.user.id}
            />
            {/* Keyed by project so panel state (replacing a photo, retry keys) never leaks between projects. */}
            <ProjectStatusPanel
              key={project.data.id}
              project={project.data}
              accessToken={session.access_token}
              userId={session.user.id}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}
