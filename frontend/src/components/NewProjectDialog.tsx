import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createProject } from "../api/client";
import { projectsQueryKey } from "../hooks/useProjects";
import type { Project } from "../schemas/projects";
import {
  checkImageFileBasics,
  defaultProjectName,
  type UploadStage,
  uploadSourceImage,
  uploadStageMessage,
  validateSourceImage,
} from "../sourceImageUpload";
import { Dialog } from "./Dialog";
import { CheckIcon } from "./Icons";
import { PhotoPicker } from "./PhotoPicker";

const MAX_PROJECT_NAME_LENGTH = 100;
const PHOTO_TIPS = ["One object, fully in the frame", "Plain, uncluttered background", "Even light, no harsh shadows"];

type CreationStage = "idle" | "creating" | UploadStage;

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
      description="Start with a photo of the object you want to build."
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
  const photoInputId = useId();
  const nameInputId = useId();
  const [photo, setPhoto] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [stage, setStage] = useState<CreationStage>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Remembers a project created before a failed upload, so "Try again" never creates a duplicate.
  const [createdProject, setCreatedProject] = useState<Project | null>(null);
  const isBusy = stage !== "idle";

  function handlePhotoSelected(selected: File) {
    const problem = checkImageFileBasics(selected);
    setErrorMessage(problem);
    setPhoto(problem ? null : selected);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!photo || isBusy) {
      return;
    }

    setErrorMessage(null);
    setStage("validating");
    const validationProblem = await validateSourceImage(photo);
    if (validationProblem) {
      setStage("idle");
      setErrorMessage(validationProblem);
      return;
    }

    let project = createdProject;
    try {
      if (!project) {
        setStage("creating");
        project = await createProject(accessToken, name.trim() || defaultProjectName(photo.name));
        setCreatedProject(project);
      }
      await uploadSourceImage({ accessToken, projectId: project.id, file: photo, onStage: setStage });
      await queryClient.invalidateQueries({ queryKey: projectsQueryKey(userId) });
      onDone();
      navigate(`/projects/${project.id}`);
    } catch {
      setStage("idle");
      setErrorMessage(
        project
          ? "Your project was created, but the photo did not upload. Please try again."
          : "We could not create the project. Please try again.",
      );
    }
  }

  return (
    <form className="dialog__form" onSubmit={(event) => void handleSubmit(event)}>
      <PhotoPicker inputId={photoInputId} file={photo} onSelect={handlePhotoSelected} disabled={isBusy} />

      <div className="photo-tips">
        <span className="photo-tips__title">For the best 3D model</span>
        <ul>
          {PHOTO_TIPS.map((tip) => (
            <li key={tip}>
              <CheckIcon size={16} />
              {tip}
            </li>
          ))}
        </ul>
      </div>

      <label className="field-label" htmlFor={nameInputId}>
        Project name <span className="field-label__optional">(optional)</span>
      </label>
      <input
        id={nameInputId}
        className="text-input"
        value={name}
        maxLength={MAX_PROJECT_NAME_LENGTH}
        placeholder={photo ? defaultProjectName(photo.name) : "e.g. Toy robot"}
        onChange={(event) => setName(event.target.value)}
        disabled={isBusy || createdProject !== null}
      />
      <p className="field-help">Leave blank to use the photo’s file name.</p>

      {errorMessage ? <p className="form-error" role="alert">{errorMessage}</p> : null}
      {isBusy ? (
        <p className="status status--pending" role="status">
          {stage === "creating" ? "Creating your project…" : uploadStageMessage(stage)}
        </p>
      ) : null}

      <div className="dialog__actions">
        <button type="button" className="button button--secondary" onClick={onDone} disabled={isBusy}>
          Cancel
        </button>
        <button type="submit" className="button" disabled={!photo || isBusy}>
          {createdProject ? "Try again" : "Create project"}
        </button>
      </div>
    </form>
  );
}
