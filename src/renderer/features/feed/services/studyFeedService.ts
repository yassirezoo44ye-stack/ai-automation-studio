import { API, apiFetch } from "../../../shared/utils/api";
import type { FeedItem } from "../types/feed.types";

export async function loadStudyItems(): Promise<FeedItem[]> {
  const response = await apiFetch("/api/study-library/catalog?limit=30&offset=0");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const { lessons } = await response.json();
  return lessons.map((lesson: { slug: string; title: string; description: string; subject: string }) => ({
    id: `study:${lesson.slug}`,
    type: "STUDY",
    title: lesson.title,
    description: lesson.description,
    creator: { id: "flow-study", name: "Flow", handle: "@flow" },
    media: { type: "image", src: `${API}/api/study-library/lessons/${encodeURIComponent(lesson.slug)}/cover` },
    tags: [lesson.subject],
    likes: 0, comments: 0, shares: 0, saves: 0,
    ctaType: "use-template",
    targetPage: "study-library",
    sourceId: lesson.slug,
    sourceType: "slug",
  }));
}
