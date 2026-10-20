import { Camera, ImageIcon } from "lucide-react";
import { useEffect, useMemo, useRef, type ReactNode } from "react";

import { useI18n } from "../i18n";
import { haptic } from "../telegram";

/**
 * Add one photo (proof, receipt, Z-report, selfie, document scan). With `capture` the big button
 * opens the camera directly and a small link offers the gallery; without it the phone asks.
 * After picking: a thumbnail, the file name and Remove. The server re-encodes every image.
 */
export function PhotoInput({
  value,
  onChange,
  capture,
  accept = "image/*",
  label,
  disabled,
}: {
  value: File | null;
  onChange: (file: File | null) => void;
  /** "environment" for receipts and documents, "user" for selfies. */
  capture?: "environment" | "user";
  accept?: string;
  /** Text in the drop area (default "Take or choose a photo" / "Take a photo"). */
  label?: ReactNode;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);
  const preview = useMemo(() => (value ? URL.createObjectURL(value) : null), [value]);
  useEffect(() => () => (preview ? URL.revokeObjectURL(preview) : undefined), [preview]);

  const picked = (input: HTMLInputElement) => {
    const file = input.files?.[0] ?? null;
    // Clear the input so picking the same photo again after Remove still fires a change.
    input.value = "";
    if (file) haptic();
    onChange(file);
  };

  return (
    <>
      <input ref={gallery} type="file" accept={accept} hidden onChange={(event) => picked(event.target)} />
      {capture && <input ref={camera} type="file" accept={accept} capture={capture} hidden onChange={(event) => picked(event.target)} />}
      {value && preview ? (
        <div className="ui-photo">
          <img className="ui-photo-thumb" src={preview} alt="" />
          <div className="ui-photo-text">
            <div className="ui-photo-title">{t("ui.photo.added")}</div>
            <div className="ui-photo-name">{value.name}</div>
          </div>
          <button type="button" className="btn btn-ghost" onClick={() => onChange(null)} disabled={disabled}>
            {t("ui.photo.remove")}
          </button>
        </div>
      ) : (
        <div className="ui-photo-pick">
          <button type="button" className="photo-drop" disabled={disabled} onClick={() => (capture ? camera : gallery).current?.click()}>
            <span className="circle ui-photo-icon">
              <Camera size={22} strokeWidth={2.4} aria-hidden />
            </span>
            <span>{label ?? t(capture ? "ui.photo.camera" : "ui.photo.add")}</span>
          </button>
          {capture && (
            <button type="button" className="btn btn-ghost ui-photo-gallery" disabled={disabled} onClick={() => gallery.current?.click()}>
              <ImageIcon size={17} strokeWidth={2.5} aria-hidden />
              <span>{t("ui.photo.gallery")}</span>
            </button>
          )}
        </div>
      )}
    </>
  );
}
