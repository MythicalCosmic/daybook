/**
 * The receipts of a new expense: up to five photos or PDF files. The big button opens the camera
 * (a receipt is photographed far more often than picked), the link under it the gallery or the
 * files, several at once. Each file is a tile with Remove: a photo shows itself, a PDF its icon.
 */
import { Camera, FileText, Paperclip, X } from "lucide-react";
import { useRef } from "react";

import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Button, useFieldControl, useObjectUrl } from "../../ui";
import { addReceipts, isImage, MAX_RECEIPTS, RECEIPT_ACCEPT } from "./lib";
import { useExpensesT } from "./text";

/** A stable key per picked file, so removing one doesn't redraw the others' previews. */
const keys = new WeakMap<File, number>();
let lastKey = 0;
function keyOf(file: File): number {
  let key = keys.get(file);
  if (key === undefined) {
    lastKey += 1;
    key = lastKey;
    keys.set(file, key);
  }
  return key;
}

export function ReceiptsInput({ value, onChange, disabled }: { value: readonly File[]; onChange: (files: File[]) => void; disabled?: boolean }) {
  const t = useExpensesT();
  const toast = useToast();
  const control = useFieldControl();
  const camera = useRef<HTMLInputElement>(null);
  const files = useRef<HTMLInputElement>(null);

  const picked = (input: HTMLInputElement) => {
    const list = [...(input.files ?? [])];
    // Clear the input so picking the same file again after Remove still fires a change.
    input.value = "";
    if (!list.length) return;
    const added = addReceipts(value, list);
    if (added.dropped) {
      haptic.notify("warning");
      toast(t(added.dropped === "limit" ? "receipts.limit" : "receipts.type"), { tone: "error" });
    }
    if (added.files.length === value.length) return;
    haptic();
    onChange(added.files);
  };
  const remove = (file: File) => {
    haptic.select();
    onChange(value.filter((item) => item !== file));
  };
  const room = value.length < MAX_RECEIPTS;

  return (
    <div className="exp-receipts">
      <input ref={files} type="file" accept={RECEIPT_ACCEPT} multiple hidden onChange={(event) => picked(event.target)} />
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(event) => picked(event.target)} />
      {value.length > 0 && (
        <ul className="exp-tiles">
          {value.map((file, index) => (
            <PickedTile key={keyOf(file)} file={file} number={index + 1} disabled={disabled} onRemove={() => remove(file)} />
          ))}
        </ul>
      )}
      {room &&
        (value.length === 0 ? (
          <div className="ui-photo-pick">
            <button {...control} type="button" className="photo-drop" disabled={disabled} onClick={() => camera.current?.click()}>
              <span className="circle ui-photo-icon">
                <Camera size={22} strokeWidth={2.4} aria-hidden />
              </span>
              <span>{t("receipts.camera")}</span>
            </button>
            <button type="button" className="btn btn-ghost ui-photo-gallery" disabled={disabled} onClick={() => files.current?.click()}>
              <Paperclip size={17} strokeWidth={2.5} aria-hidden />
              <span>{t("receipts.file")}</span>
            </button>
          </div>
        ) : (
          <div className="exp-receipts-more">
            <Button variant="secondary" icon={Camera} disabled={disabled} onClick={() => camera.current?.click()}>
              {t("receipts.photo")}
            </Button>
            <Button variant="ghost" icon={Paperclip} disabled={disabled} onClick={() => files.current?.click()}>
              {t("receipts.more")}
            </Button>
          </div>
        ))}
    </div>
  );
}

function PickedTile({ file, number, disabled, onRemove }: { file: File; number: number; disabled?: boolean; onRemove: () => void }) {
  const t = useExpensesT();
  const image = isImage(file);
  // Only a photo gets a preview; a PDF is shown by its icon.
  const preview = useObjectUrl(image ? file : null);
  return (
    <li className="exp-tile">
      {image ? (
        // The preview arrives an effect after the pick; a blank tile holds its place meanwhile.
        preview ? (
          <img className="exp-tile-img" src={preview} alt={t("receipts.item", { number })} />
        ) : (
          <span className="exp-tile-img exp-tile-img--empty" aria-hidden />
        )
      ) : (
        <span className="exp-tile-file" title={file.name}>
          <FileText size={24} strokeWidth={2.2} aria-hidden />
          <span>{t("receipts.pdf")}</span>
        </span>
      )}
      <button type="button" className="exp-tile-remove" aria-label={t("receipts.remove", { name: file.name })} disabled={disabled} onClick={onRemove}>
        <X size={15} strokeWidth={3} aria-hidden />
      </button>
    </li>
  );
}
