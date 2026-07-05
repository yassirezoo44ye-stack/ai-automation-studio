/**
 * Design Studio Event Definitions.
 * Every cross-module communication goes through these typed events.
 * Nothing communicates directly — everything emits events.
 */
import type { FabricObject } from "fabric";
import type { ElementMeta } from "../../types/canvas.types";

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

export interface BrandKitChangedEvent { kitId: string }

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
