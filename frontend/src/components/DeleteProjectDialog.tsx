import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, deleteProject } from "../api/client";
import { isNotFound, projectQueryKey, projectsQueryKey } from "../hooks/useProjects";
import { Dialog } from "./Dialog";

interface DeleteProjectDialogProps {
  isOpen: boolean;
  onClose: () => void;
  accessToken: string;
  userId: string;
  projectId: string;
  projectName: string;
}

export function DeleteProjectDialog({
  isOpen,
  onClose,
  accessToken,
  userId,
  projectId,
  projectName,
}: DeleteProjectDialogProps) {
  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      title="Delete this project?"
      description={`“${projectName}” and its photo, 3D model and LEGO build will be removed. This cannot be undone.`}
    >
      <DeleteProjectForm
        accessToken={accessToken}
        userId={userId}
        projectId={projectId}
        onCancel={onClose}
      />
    </Dialog>
  );
}

interface DeleteProjectFormProps {
  accessToken: string;
  userId: string;
  projectId: string;
  onCancel: () => void;
}

function DeleteProjectForm({ accessToken, userId, projectId, onCancel }: DeleteProjectFormProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isDeleting, setIsDeleting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleDelete() {
    if (isDeleting) {
      return;
    }
    setErrorMessage(null);
    setIsDeleting(true);
    try {
      await deleteProject(accessToken, projectId);
    } catch (error) {
      // Already deleted (for example in another tab): the user's goal is reached.
      if (!isNotFound(error)) {
        setIsDeleting(false);
        setErrorMessage(deleteErrorMessage(error));
        return;
      }
    }
    // Leave the page before dropping its cached data, so it never flashes "Project not found".
    navigate("/");
    queryClient.removeQueries({ queryKey: projectQueryKey(userId, projectId) });
    await queryClient.invalidateQueries({ queryKey: projectsQueryKey(userId) });
  }

  return (
    <div className="dialog__form">
      {errorMessage ? <p className="form-error" role="alert">{errorMessage}</p> : null}
      <div className="dialog__actions">
        <button type="button" className="button button--secondary" onClick={onCancel} disabled={isDeleting}>
          Cancel
        </button>
        <button
          type="button"
          className="button button--danger"
          onClick={() => void handleDelete()}
          disabled={isDeleting}
        >
          {isDeleting ? "Deleting…" : "Delete project"}
        </button>
      </div>
    </div>
  );
}

function deleteErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "This project has a job in progress. Wait for it to finish, then try again.";
  }
  return "We could not delete the project. Please try again.";
}
