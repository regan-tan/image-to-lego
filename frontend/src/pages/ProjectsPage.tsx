import { useState } from "react";
import { Link } from "react-router-dom";

import { useAppLayout } from "../components/appLayoutContext";
import { CubeIcon, ImageIcon, PlusIcon } from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import { useArtifactReadUrl } from "../hooks/useArtifactReadUrl";
import { useProjects } from "../hooks/useProjects";
import type { Project } from "../schemas/projects";

const projectDateFormat = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function ProjectsPage() {
  const { session, openNewProject, openHowItWorks } = useAppLayout();
  const projects = useProjects(session.access_token, session.user.id);
  const projectList = projects.data ?? [];
  const hasProjects = projectList.length > 0;

  return (
    <div className="page__container">
      <div className="page-heading">
        <div>
          <h1>Projects</h1>
          {hasProjects ? (
            <p className="page-heading__meta">
              {projectList.length} {projectList.length === 1 ? "project" : "projects"}
            </p>
          ) : null}
        </div>
        {hasProjects ? (
          <button type="button" className="button" onClick={openNewProject}>
            <PlusIcon />
            New project
          </button>
        ) : null}
      </div>

      {projects.isPending ? <p className="status status--pending" role="status">Loading projects…</p> : null}
      {projects.isError ? (
        <div className="form-error" role="alert">
          <p>We could not load your projects.</p>
          <button className="text-button" type="button" onClick={() => void projects.refetch()}>
            Try again
          </button>
        </div>
      ) : null}

      {projects.isSuccess && !hasProjects ? (
        <EmptyBaseplate onNewProject={openNewProject} onHowItWorks={openHowItWorks} />
      ) : null}

      {hasProjects ? (
        <ul className="project-grid">
          {projectList.map((project) => (
            <li key={project.id}>
              <ProjectCard project={project} accessToken={session.access_token} userId={session.user.id} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

interface ProjectCardProps {
  project: Project;
  accessToken: string;
  userId: string;
}

function ProjectCard({ project, accessToken, userId }: ProjectCardProps) {
  return (
    <Link to={`/projects/${project.id}`} className="project-card">
      <div className="project-card__thumbnail baseplate">
        <ProjectThumbnail project={project} accessToken={accessToken} userId={userId} />
      </div>
      <div className="project-card__body">
        <h2 className="project-card__name">{project.name}</h2>
        <div className="project-card__footer">
          <StatusBadge status={project.status} />
          <p className="project-card__meta">Updated {projectDateFormat.format(new Date(project.updatedAt))}</p>
        </div>
      </div>
    </Link>
  );
}

function ProjectThumbnail({ project, accessToken, userId }: ProjectCardProps) {
  const readUrl = useArtifactReadUrl(accessToken, userId, project.sourceImageArtifactId);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const url = readUrl.data?.url;

  if (url && failedUrl !== url) {
    // Decorative: the card's link text already names the project.
    return (
      <img
        className="project-card__photo"
        src={url}
        alt=""
        loading="lazy"
        onError={() => setFailedUrl(url)}
      />
    );
  }
  return (
    <span className="project-card__thumbnail-icon">
      {project.status === "model_ready" ? <CubeIcon size={28} /> : <ImageIcon size={26} />}
    </span>
  );
}

interface EmptyBaseplateProps {
  onNewProject: () => void;
  onHowItWorks: () => void;
}

function EmptyBaseplate({ onNewProject, onHowItWorks }: EmptyBaseplateProps) {
  return (
    <section className="empty-baseplate baseplate baseplate--large" aria-labelledby="empty-projects-title">
      <div className="empty-baseplate__card">
        <svg width="112" height="66" viewBox="0 0 112 66" aria-hidden="true" focusable="false">
          <g fill="#ffcd00">
            <rect x="10" y="2" width="16" height="11" rx="3" />
            <rect x="36" y="2" width="16" height="11" rx="3" />
            <rect x="62" y="2" width="16" height="11" rx="3" />
            <rect x="88" y="2" width="16" height="11" rx="3" />
            <rect x="2" y="11" width="108" height="53" rx="6" />
          </g>
          <rect x="2" y="54" width="108" height="10" rx="5" fill="#d9a900" />
        </svg>
        <div className="empty-baseplate__text">
          <h2 id="empty-projects-title">Your baseplate is empty</h2>
          <p>Add a photo of any object. We’ll turn it into a 3D model, then into a LEGO build.</p>
        </div>
        <div className="button-row">
          <button type="button" className="button" onClick={onNewProject}>
            <PlusIcon />
            New project
          </button>
          <button type="button" className="button button--secondary" onClick={onHowItWorks}>
            How it works
          </button>
        </div>
      </div>
    </section>
  );
}
