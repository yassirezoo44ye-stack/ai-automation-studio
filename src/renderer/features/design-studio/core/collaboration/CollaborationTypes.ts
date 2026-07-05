/**
 * Collaboration Foundation — types-only layer.
 * No real-time backend is required yet, but every model is defined
 * so a WebSocket or CRDT backend can plug in without architectural changes.
 */

// ── Presence ──────────────────────────────────────────────────────────────────

export interface Cursor {
  x: number;
  y: number;
  pageId: string;
}

export interface CollaboratorPresence {
  userId:    string;
  name:      string;
  avatar?:   string;
  color:     string;          // Assigned cursor/highlight colour
  cursor?:   Cursor;
  selection: string[];        // Selected object IDs
  lastSeen:  number;          // Unix ms
  isActive:  boolean;
}

// ── Comments ──────────────────────────────────────────────────────────────────

export interface CommentAnchor {
  pageId:   string;
  x:        number;
  y:        number;
  objectId?: string;
}

export interface CommentReply {
  id:        string;
  authorId:  string;
  body:      string;
  createdAt: string;
  updatedAt: string;
}

export interface Comment {
  id:        string;
  anchor:    CommentAnchor;
  authorId:  string;
  body:      string;
  replies:   CommentReply[];
  resolved:  boolean;
  createdAt: string;
  updatedAt: string;
}

// ── Change events ─────────────────────────────────────────────────────────────
// Type definitions for future conflict-resolution support.
// No real-time backend is wired yet; NoopCollaborationProvider is the live impl.

export type ChangeOpType =
  | "add"
  | "remove"
  | "update"
  | "move"
  | "resize"
  | "rotate"
  | "reorder"
  | "page_add"
  | "page_remove";

export interface ChangeOp {
  id:        string;
  type:      ChangeOpType;
  userId:    string;
  pageId:    string;
  objectId?: string;
  payload:   Record<string, unknown>;
  timestamp: number;
  version:   number;
}

// ── Session state ─────────────────────────────────────────────────────────────

export interface CollaborationSession {
  sessionId:    string;
  projectId:    string;
  participants: CollaboratorPresence[];
  comments:     Comment[];
  version:      number;           // Monotonically increasing operation counter
}

// ── Provider interface (to be implemented by WS/WebRTC backend) ───────────────

export interface CollaborationProvider {
  connect(sessionId: string, userId: string): Promise<void>;
  disconnect(): void;
  sendPresence(presence: Partial<CollaboratorPresence>): void;
  sendOp(op: ChangeOp): void;
  addComment(comment: Omit<Comment, "id" | "createdAt" | "updatedAt">): Promise<Comment>;
  resolveComment(commentId: string): Promise<void>;
  onPresenceChange(cb: (presence: CollaboratorPresence) => void): () => void;
  onOp(cb: (op: ChangeOp) => void): () => void;
  onComment(cb: (comment: Comment) => void): () => void;
}

// ── No-op provider (default until backend is wired up) ────────────────────────

export class NoopCollaborationProvider implements CollaborationProvider {
  async connect() { /* not yet connected */ }
  disconnect() { /* noop */ }
  sendPresence() { /* noop */ }
  sendOp() { /* noop */ }
  async addComment(c: Omit<Comment, "id" | "createdAt" | "updatedAt">): Promise<Comment> {
    const now = new Date().toISOString();
    return { ...c, id: `cm_${Date.now()}`, createdAt: now, updatedAt: now };
  }
  async resolveComment() { /* noop */ }
  onPresenceChange() { return () => {}; }
  onOp() { return () => {}; }
  onComment() { return () => {}; }
}
