/**
 * Design Studio Event Definitions.
 * Every cross-module communication goes through these typed events.
 * Nothing communicates directly — everything emits events.
 */
import type { FabricObject } from "fabric";
import type { ElementMeta } from "../../types/canvas.types";
import type { FullBrandKit } from "../../features/brand-kit/BrandKit";

// ── Object events ─────────────────────────────────────────────────────────────

export interface ObjectCreatedEvent {
  objectId: string;
  meta: ElementMeta;
  fabricObject: FabricObject;
}

export interface ObjectUpdatedEvent {
  objectId: string;
  changes: Record<string, unknown>;
}

export interface ObjectDeletedEvent {
  objectId: string;
  meta: ElementMeta;
}

export interface SelectionChangedEvent {
  selectedIds: string[];
  previousIds: string[];
}

// ── Page events ───────────────────────────────────────────────────────────────

export interface PageCreatedEvent  { pageId: string; name: string }
export interface PageDeletedEvent  { pageId: string }
export interface PageRenamedEvent  { pageId: string; name: string }
export interface PageReorderedEvent { from: number; to: number }

// ── Export events ─────────────────────────────────────────────────────────────

export interface ExportStartedEvent  { format: string; pageIds: string[] }
export interface ExportFinishedEvent { format: string; filename: string; bytes: number }
export interface ExportFailedEvent   { format: string; error: string }

// ── Import events ─────────────────────────────────────────────────────────────

export interface AssetImportedEvent  { assetId: string; name: string; type: string }
export interface TemplateAppliedEvent { templateId: string; name: string; pageId: string }

// ── Command events ────────────────────────────────────────────────────────────

export interface CommandExecutedEvent { description: string }
export interface CommandUndoneEvent   { description: string }
export interface CommandRedoneEvent   { description: string }

// ── Token events ──────────────────────────────────────────────────────────────

export interface TokenCreatedEvent { tokenId: string; name: string; category: string }
export interface TokenUpdatedEvent { tokenId: string; oldValue: unknown; newValue: unknown }
export interface TokenDeletedEvent { tokenId: string }

// ── Brand Kit events ──────────────────────────────────────────────────────────

/**
 * Contract for BrandKitChanged (see BrandKitService — the only emitter):
 *
 * Event:   BrandKitChanged
 * Payload: { kitId: string; kit: FullBrandKit }
 *
 * Fires when:
 *   - BrandKitService.save() persists a kit successfully.
 *   - BrandKitService.setActive() switches the active kit successfully.
 *
 * Guarantees:
 *   - Fired after successful persistence — never before the IndexedDB write
 *     that caused it has completed.
 *   - Fired exactly once per successful mutation; never fired on a failed
 *     or no-op write (e.g. save() before init() has opened the DB).
 *   - `kit` is the exact object that was just persisted/activated — safe
 *     to consume directly, no need to re-read brandKitService.active.
 *   - `kitId` always refers to `kit.id` (kept alongside `kit` for callers
 *     that only care about identity, not the full payload).
 *   - One-directional: this event never carries Design Token data, and
 *     TokenRegistry must never be the trigger for a BrandKitChanged emit
 *     (see the Architecture Decision doc — BrandKit → Tokens is one-way).
 */
export interface BrandKitChangedEvent { kitId: string; kit: FullBrandKit }

// ── Component events ──────────────────────────────────────────────────────────

export interface ComponentCreatedEvent  { componentId: string; name: string }
export interface ComponentUpdatedEvent  { componentId: string }
export interface ComponentInstanceSyncedEvent { componentId: string; instanceIds: string[] }

// ── Plugin events ─────────────────────────────────────────────────────────────

export interface PluginRegisteredEvent   { pluginId: string; name: string }
export interface PluginUnregisteredEvent { pluginId: string }

// ── Collaboration events ──────────────────────────────────────────────────────

export interface PresenceUpdatedEvent { userId: string; cursor?: { x: number; y: number } }
export interface CommentAddedEvent    { commentId: string; pageId: string }

// ── Map: event name → payload type ───────────────────────────────────────────

export interface DesignEventMap {
  ObjectCreated:           ObjectCreatedEvent;
  ObjectUpdated:           ObjectUpdatedEvent;
  ObjectDeleted:           ObjectDeletedEvent;
  SelectionChanged:        SelectionChangedEvent;
  PageCreated:             PageCreatedEvent;
  PageDeleted:             PageDeletedEvent;
  PageRenamed:             PageRenamedEvent;
  PageReordered:           PageReorderedEvent;
  ExportStarted:           ExportStartedEvent;
  ExportFinished:          ExportFinishedEvent;
  ExportFailed:            ExportFailedEvent;
  AssetImported:           AssetImportedEvent;
  TemplateApplied:         TemplateAppliedEvent;
  CommandExecuted:         CommandExecutedEvent;
  CommandUndone:           CommandUndoneEvent;
  CommandRedone:           CommandRedoneEvent;
  TokenCreated:            TokenCreatedEvent;
  TokenUpdated:            TokenUpdatedEvent;
  TokenDeleted:            TokenDeletedEvent;
  BrandKitChanged:         BrandKitChangedEvent;
  ComponentCreated:        ComponentCreatedEvent;
  ComponentUpdated:        ComponentUpdatedEvent;
  ComponentInstanceSynced: ComponentInstanceSyncedEvent;
  PluginRegistered:        PluginRegisteredEvent;
  PluginUnregistered:      PluginUnregisteredEvent;
  PresenceUpdated:         PresenceUpdatedEvent;
  CommentAdded:            CommentAddedEvent;
}

export type DesignEventName = keyof DesignEventMap;
