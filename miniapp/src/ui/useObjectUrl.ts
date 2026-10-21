import { useEffect, useState } from "react";

/**
 * A `blob:` URL for previewing a picked file, revoked when the file changes or the component
 * goes away. The URL is made and revoked in the same effect: StrictMode's extra mount and
 * unmount then revoke only a URL nobody shows, and the one on screen stays valid (a URL made in
 * `useMemo` and revoked in an effect cleanup is gone after that extra unmount). Null until the
 * effect has run and while there is no file.
 */
export function useObjectUrl(file: Blob | null | undefined): string | null {
  const [made, setMade] = useState<{ file: Blob; url: string } | null>(null);
  useEffect(() => {
    if (!file) {
      setMade(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setMade({ file, url });
    return () => URL.revokeObjectURL(url);
  }, [file]);
  // A URL made for an earlier file is never handed out for this one.
  return made && made.file === file ? made.url : null;
}
