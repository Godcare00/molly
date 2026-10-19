import { api, API_BASE_URL, getActiveWorkerId } from './client';
import type { FileResponse } from '@/types/api';

function workerPrefixed(path: string): string {
  const workerId = getActiveWorkerId();
  return workerId ? `/w/${workerId}${path}` : path;
}

export const filesApi = {
  list: (conversationId: string, limit = 50) =>
    api.get<FileResponse[]>(`/conversations/${conversationId}/files`, { query: { limit } }),

  get: (conversationId: string, fileId: string) =>
    api.get<FileResponse>(`/conversations/${conversationId}/files/${fileId}`),

  remove: (conversationId: string, fileId: string) =>
    api.delete<void>(`/conversations/${conversationId}/files/${fileId}`),

  markViewed: (conversationId: string, fileId: string) =>
    api.post<void>(`/conversations/${conversationId}/files/${fileId}/view`),

  /** Uploads a locally-picked document as multipart/form-data. */
  async upload(conversationId: string, localUri: string, fileName: string, mimeType: string) {
    const form = new FormData();
    // React Native's FormData accepts this special-shaped object for file uploads.
    form.append('file', {
      uri: localUri,
      name: fileName,
      type: mimeType,
    } as unknown as Blob);

    return api.post<FileResponse>(`/conversations/${conversationId}/files`, form, { isForm: true });
  },

  /** Builds an authenticated URL for referencing an already-uploaded file. */
  resolveUrl(path: string) {
    return path.startsWith('http') ? path : `${API_BASE_URL}${workerPrefixed(path)}`;
  },

  /** Builds the URL for downloading a file's actual bytes (GET .../content) —
   * use this instead of resolveUrl(path), which prepends the API base to the
   * file's server-side disk path and doesn't correspond to a real route. */
  contentUrl(conversationId: string, fileId: string) {
    return `${API_BASE_URL}${workerPrefixed(`/conversations/${conversationId}/files/${fileId}/content`)}`;
  },
};
