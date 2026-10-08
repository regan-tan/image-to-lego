import { type DragEvent, useEffect, useRef, useState } from "react";

import { ACCEPTED_IMAGE_TYPES, formatMaxImageSize } from "../sourceImageUpload";
import { UploadIcon } from "./Icons";

interface PhotoPickerProps {
  inputId: string;
  file: File | null;
  onSelect: (file: File) => void;
  disabled?: boolean;
}

/** A file input styled as a studded drop zone; shows a local preview once a photo is chosen. */
export function PhotoPicker({ inputId, file, onSelect, disabled = false }: PhotoPickerProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [preview, setPreview] = useState<{ file: File; url: string } | null>(null);
  const latestPreviewUrl = useRef<string | null>(null);
  // Only show the preview while the parent still holds this file (it may reject an invalid one).
  const previewUrl = preview && preview.file === file ? preview.url : null;

  // Release the last preview's memory when the picker goes away.
  useEffect(() => () => {
    if (latestPreviewUrl.current) {
      URL.revokeObjectURL(latestPreviewUrl.current);
    }
  }, []);

  function selectFile(selected: File) {
    if (latestPreviewUrl.current) {
      URL.revokeObjectURL(latestPreviewUrl.current);
    }
    const url = URL.createObjectURL(selected);
    latestPreviewUrl.current = url;
    setPreview({ file: selected, url });
    onSelect(selected);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(false);
    const dropped = event.dataTransfer.files[0];
    if (dropped && !disabled) {
      selectFile(dropped);
    }
  }

  return (
    <label
      htmlFor={inputId}
      className={`photo-picker baseplate${isDragging ? " photo-picker--dragging" : ""}${disabled ? " photo-picker--disabled" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
    >
      {file && previewUrl ? (
        <>
          <img className="photo-picker__preview" src={previewUrl} alt="" />
          <span className="photo-picker__text">
            <span className="photo-picker__title">{file.name}</span>
            <span className="photo-picker__hint">Choose a different photo</span>
          </span>
        </>
      ) : (
        <>
          <span className="photo-picker__icon">
            <UploadIcon size={24} />
          </span>
          <span className="photo-picker__text">
            <span className="photo-picker__title">
              Drag a photo here or <span className="photo-picker__browse">browse</span>
            </span>
            <span className="photo-picker__hint">JPEG, PNG or WebP, up to {formatMaxImageSize()}</span>
          </span>
        </>
      )}
      <input
        id={inputId}
        className="visually-hidden"
        type="file"
        accept={ACCEPTED_IMAGE_TYPES}
        disabled={disabled}
        onChange={(event) => {
          const selected = event.target.files?.[0];
          // Reset so choosing the same file again still fires a change event.
          event.target.value = "";
          if (selected) {
            selectFile(selected);
          }
        }}
      />
    </label>
  );
}
