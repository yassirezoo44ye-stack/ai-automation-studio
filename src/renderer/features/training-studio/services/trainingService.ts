/**
 * Training Studio API service.
 *
 * All calls go through apiFetch (token + org-id headers injected).
 * Every function returns typed data or throws on non-2xx.
 */
import { apiJSON } from "../../../shared/utils/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Course {
  id: string;
  organization_id: string;
  project_id: string | null;
  title: string;
  description: string | null;
  status: "draft" | "published" | "archived";
  source_type: string | null;
  language: string;
  created_at: string;
  updated_at: string;
}

export interface Lesson {
  id: string;
  course_id: string;
  organization_id: string;
  title: string;
  description: string | null;
  position: number;
  status: "draft" | "published";
  duration_seconds: number | null;
  created_at: string;
  updated_at: string;
}

export interface Script {
  id: string;
  lesson_id: string | null;
  organization_id: string;
  content: string;
  language: string;
  generated_by: string;
  model_used: string | null;
  created_at: string;
  updated_at: string;
}

export interface Video {
  id: string;
  lesson_id: string | null;
  organization_id: string;
  title: string | null;
  provider: string;
  provider_video_id: string | null;
  status: "draft" | "queued" | "processing" | "completed" | "failed" | "cancelled";
  url: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  language: string;
  created_at: string;
  updated_at: string;
}

export interface Quiz {
  id: string;
  lesson_id: string | null;
  organization_id: string;
  title: string;
  pass_score: number;
  created_at: string;
  updated_at: string;
}

export interface Question {
  id: string;
  quiz_id: string;
  organization_id: string;
  question_text: string;
  question_type: "multiple_choice" | "true_false" | "knowledge_check";
  options: unknown[];
  correct_answer: number | null;
  explanation: string | null;
  position: number;
  created_at: string;
}

export interface Learner {
  id: string;
  organization_id: string;
  email: string;
  name: string | null;
  created_at: string;
}

export interface Job {
  id: string;
  organization_id: string;
  job_type: string;
  reference_id: string | null;
  reference_type: string | null;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface VideoProvider {
  provider_id: string;
  display_name: string;
}

// ── Courses ───────────────────────────────────────────────────────────────────

export async function listCourses(params?: { status?: string; language?: string; limit?: number; offset?: number }): Promise<Course[]> {
  const q = new URLSearchParams();
  if (params?.status)   q.set("status",   params.status);
  if (params?.language) q.set("language", params.language);
  if (params?.limit)    q.set("limit",    String(params.limit));
  if (params?.offset)   q.set("offset",   String(params.offset));
  const qs = q.toString() ? `?${q}` : "";
  return apiJSON<Course[]>(`/api/training/courses${qs}`);
}

export async function createCourse(data: {
  title: string;
  description?: string;
  language?: string;
  source_type?: string;
}): Promise<Course> {
  return apiJSON<Course>("/api/training/courses", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getCourse(id: string): Promise<Course> {
  return apiJSON<Course>(`/api/training/courses/${id}`);
}

export async function updateCourse(id: string, data: {
  title?: string;
  description?: string;
  status?: string;
  language?: string;
}): Promise<Course> {
  return apiJSON<Course>(`/api/training/courses/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteCourse(id: string): Promise<void> {
  await apiJSON<void>(`/api/training/courses/${id}`, { method: "DELETE" });
}

// ── Lessons ───────────────────────────────────────────────────────────────────

export async function listLessons(courseId: string): Promise<Lesson[]> {
  return apiJSON<Lesson[]>(`/api/training/courses/${courseId}/lessons`);
}

export async function createLesson(courseId: string, data: {
  title: string;
  description?: string;
  position?: number;
}): Promise<Lesson> {
  return apiJSON<Lesson>(`/api/training/courses/${courseId}/lessons`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateLesson(lessonId: string, data: {
  title?: string;
  description?: string;
  position?: number;
  status?: string;
}): Promise<Lesson> {
  return apiJSON<Lesson>(`/api/training/lessons/${lessonId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteLesson(lessonId: string): Promise<void> {
  await apiJSON<void>(`/api/training/lessons/${lessonId}`, { method: "DELETE" });
}

// ── Scripts ───────────────────────────────────────────────────────────────────

export async function listScripts(lessonId: string): Promise<Script[]> {
  return apiJSON<Script[]>(`/api/training/lessons/${lessonId}/scripts`);
}

export async function createScript(lessonId: string, data: {
  content: string;
  language?: string;
  generated_by?: string;
}): Promise<Script> {
  return apiJSON<Script>(`/api/training/lessons/${lessonId}/scripts`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ── Videos ────────────────────────────────────────────────────────────────────

export async function listVideos(lessonId: string): Promise<Video[]> {
  return apiJSON<Video[]>(`/api/training/lessons/${lessonId}/videos`);
}

export async function createVideo(lessonId: string, data: {
  title?: string;
  language?: string;
  provider?: string;
}): Promise<Video> {
  return apiJSON<Video>(`/api/training/lessons/${lessonId}/videos`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getVideo(videoId: string): Promise<Video> {
  return apiJSON<Video>(`/api/training/videos/${videoId}`);
}

export async function generateVideo(videoId: string): Promise<Video> {
  return apiJSON<Video>(`/api/training/videos/${videoId}/generate`, { method: "POST" });
}

// ── Quizzes ───────────────────────────────────────────────────────────────────

export async function listQuizzes(lessonId: string): Promise<Quiz[]> {
  return apiJSON<Quiz[]>(`/api/training/lessons/${lessonId}/quizzes`);
}

export async function createQuiz(lessonId: string, data: {
  title: string;
  pass_score?: number;
}): Promise<Quiz> {
  return apiJSON<Quiz>(`/api/training/lessons/${lessonId}/quizzes`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function addQuestion(quizId: string, data: {
  question_text: string;
  question_type?: string;
  options?: unknown[];
  correct_answer?: number | null;
  explanation?: string;
  position?: number;
}): Promise<Question> {
  return apiJSON<Question>(`/api/training/quizzes/${quizId}/questions`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ── Learners ──────────────────────────────────────────────────────────────────

export async function listLearners(params?: { limit?: number; offset?: number }): Promise<Learner[]> {
  const q = new URLSearchParams();
  if (params?.limit)  q.set("limit",  String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  const qs = q.toString() ? `?${q}` : "";
  return apiJSON<Learner[]>(`/api/training/learners${qs}`);
}

export async function createLearner(data: { email: string; name?: string }): Promise<Learner> {
  return apiJSON<Learner>("/api/training/learners", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ── Jobs ──────────────────────────────────────────────────────────────────────

export async function listJobs(params?: { status?: string; limit?: number }): Promise<Job[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.limit)  q.set("limit",  String(params.limit));
  const qs = q.toString() ? `?${q}` : "";
  return apiJSON<Job[]>(`/api/training/jobs${qs}`);
}

export async function getJob(jobId: string): Promise<Job> {
  return apiJSON<Job>(`/api/training/jobs/${jobId}`);
}

// ── Providers ─────────────────────────────────────────────────────────────────

export async function listProviders(): Promise<VideoProvider[]> {
  return apiJSON<VideoProvider[]>("/api/training/providers");
}
