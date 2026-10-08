import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createProject } from "../api/client";
import { projectsQueryKey } from "../hooks/useProjects";
import type { Project } from "../schemas/projects";
import { Dialog } from "./Dialog";

const MAX_PROJECT_NAME_LENGTH = 100;

interface NewProjectDialogProps {
  isOpen: boolean;
  onClose: () => void;
  accessToken: string;
  userId: string;
}

export function NewProjectDialog({ isOpen, onClose, accessToken, userId }: NewProjectDialogProps) {
  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      title="New project"
      description="Give your project a name. You’ll add a photo next."
    >
      <NewProjectForm accessToken={accessToken} userId={userId} onDone={onClose} />
    </Dialog>
  );
}

interface NewProjectFormProps {
  accessToken: string;
  userId: string;
  onDone: () => void;
}

function NewProjectForm({ accessToken, userId, onDone }: NewProjectFormProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const nameInputId = useId();
  const [name, setName] = useState("");
  const createProjectMutation = useMutation({
    mutationFn: (projectName: string) => createProject(accessToken, projectName),
    onSuccess: (project) => {
      queryClient.setQueryData<Project[]>(projectsQueryKey(userId), (current) => [
        project,
        ...(current ?? []),
      ]);
      onDone();
      navigate(`/projects/${project.id}`);
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (normalizedName) {
      createProjectMutation.mutate(normalizedName);
    }
  }

  return (
    <form className="dialog__form" onSubmit={handleSubmit}>
      <label className="field-label" htmlFor={nameInputId}>Project name</label>
      <input
        id={nameInputId}
        className="text-input"
        value={name}
        maxLength={MAX_PROJECT_NAME_LENGTH}
        placeholder="e.g. Toy robot"
        onChange={(event) => setName(event.target.value)}
        required
      />
      {createProjectMutation.isError ? (
        <p className="form-error" role="alert">We could not create the project. Please try again.</p>
      ) : null}
      <div className="dialog__actions">
        <button type="button" className="button button--secondary" onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className="button" disabled={createProjectMutation.isPending}>
          {createProjectMutation.isPending ? "Creating…" : "Create project"}
        </button>
      </div>
    </form>
  );
}
