/**
 * A video upload in pieces that survives a dropped connection (docs/PLAN-LEARNING.md §5): start
 * with the name and size, send `chunk_bytes` at a time in order; when a piece fails, ask the
 * server where the upload stands (its 409 says, or the video's `received_bytes`) and go on from
 * there, a few times before giving up. `resume(video)` continues an upload left half-way (the
 * same file picked again).
 */
import { isApiError } from "@/api/http";

import type { ChunkResult, Video } from "./types";

export interface UploadApi {
  startUpload: (input: { name: string; size: number }) => Promise<Video>;
  chunk: (id: number, offset: number, piece: Blob, signal?: AbortSignal) => Promise<ChunkResult>;
  video: (id: number) => Promise<Video>;
  finishUpload: (id: number) => Promise<Video>;
}

export interface UploadProgress {
  sent: number;
  total: number;
  /** 0–100. */
  percent: number;
}

export interface UploadOptions {
  onProgress?: (progress: UploadProgress) => void;
  signal?: AbortSignal;
  /** Attempts per piece before the upload gives up (default 4). */
  retries?: number;
  /** Wait before a retry, in ms (doubles each time; default 800). */
  backoff?: number;
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

/** Where the server's upload stands after a failed piece: a 409's `received_bytes`, else ask. */
async function serverOffset(api: UploadApi, id: number, error: unknown): Promise<number> {
  if (isApiError(error) && error.status === 409) {
    const body = error.body as { received_bytes?: number } | null;
    if (typeof body?.received_bytes === "number") return body.received_bytes;
  }
  return (await api.video(id)).received_bytes;
}

/** Send `file` into `video` from the server's offset on, then finish it. */
export async function sendFile(api: UploadApi, video: Video, file: File, options: UploadOptions = {}): Promise<Video> {
  const { onProgress, signal, retries = 4, backoff = 800 } = options;
  const size = file.size;
  const step = video.chunk_bytes || 8 * 1024 * 1024;
  let offset = video.received_bytes;
  let failures = 0;
  onProgress?.({ sent: offset, total: size, percent: size ? Math.floor((offset / size) * 100) : 0 });
  while (offset < size) {
    const piece = file.slice(offset, Math.min(offset + step, size), "application/octet-stream");
    try {
      const answer = await api.chunk(video.id, offset, piece, signal);
      offset = answer.received_bytes;
      failures = 0;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      failures += 1;
      if (failures > retries) throw error;
      await wait(backoff * 2 ** (failures - 1), signal);
      offset = await serverOffset(api, video.id, error);
    }
    onProgress?.({ sent: offset, total: size, percent: size ? Math.floor((offset / size) * 100) : 0 });
  }
  return api.finishUpload(video.id);
}

/** A new upload of `file`: started, sent, finished. */
export async function uploadFile(api: UploadApi, file: File, options: UploadOptions = {}): Promise<Video> {
  const video = await api.startUpload({ name: file.name, size: file.size });
  return sendFile(api, video, file, options);
}

/** The video extensions the server takes (it checks the content itself). */
export const VIDEO_ACCEPT = "video/mp4,video/quicktime,video/webm,video/x-matroska,video/3gpp,.mp4,.mov,.m4v,.webm,.mkv,.3gp";
export const MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024;
