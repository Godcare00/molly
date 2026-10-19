import { api, API_BASE_URL, getActiveWorkerId } from './client';
import { secureStorage } from '@/utils/storage';
import type { ImageResponse } from '@/types/api';

function workerPrefixed(path: string): string {
  const workerId = getActiveWorkerId();
  return workerId ? `/w/${workerId}${path}` : path;
}

export const imagesApi = {
  list: (conversationId: string, limit = 50) =>
    api.get<ImageResponse[]>(`/conversations/${conversationId}/images`, { query: { limit } }),

  get: (conversationId: string, imageId: string) =>
    api.get<ImageResponse>(`/conversations/${conversationId}/images/${imageId}`),

  remove: (conversationId: string, imageId: string) =>
    api.delete<void>(`/conversations/${conversationId}/images/${imageId}`),

  markViewed: (conversationId: string, imageId: string) =>
    api.post<void>(`/conversations/${conversationId}/images/${imageId}/view`),

  /** Uploads a locally-picked image (camera or gallery) as multipart/form-data. */
  async upload(conversationId: string, localUri: string, fileName: string, mimeType: string) {
    const form = new FormData();
    // React Native's FormData accepts this special-shaped object for file uploads.
    form.append('file', {
      uri: localUri,
      name: fileName,
      type: mimeType,
    } as unknown as Blob);

    return api.post<ImageResponse>(`/conversations/${conversationId}/images`, form, { isForm: true });
  },

  /** Builds an authenticated URL for rendering an already-uploaded image. */
  resolveUrl(path: string) {
    return path.startsWith('http') ? path : `${API_BASE_URL}${workerPrefixed(path)}`;
  },

  /** Builds the URL for downloading/displaying an image's actual bytes
   * (GET .../content) — see filesApi.contentUrl() for why this is preferred
   * over resolveUrl(path). */
  contentUrl(conversationId: string, imageId: string) {
    return `${API_BASE_URL}${workerPrefixed(`/conversations/${conversationId}/images/${imageId}/content`)}`;
  },
};
