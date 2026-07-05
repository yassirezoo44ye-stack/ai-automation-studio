import { apiFetch, parseJSON, authH, API } from "../../../shared/utils/api";

export interface YTInfo {
  title: string; channel: string; duration: number; view_count: number;
  like_count: number; description: string; thumbnail: string; upload_date: string;
}

export async function fetchYoutubeInfo(url: string): Promise<YTInfo> {
  const path = `/api/youtube/info?url=${encodeURIComponent(url)}`;
  const r = await apiFetch(path);
  return parseJSON<YTInfo>(r, path);
}

export function getSocialStreamUrl(path: string): string {
  return `${API}${path}`;
}

export function getSocialHeaders(): Record<string, string> {
  return authH();
}
