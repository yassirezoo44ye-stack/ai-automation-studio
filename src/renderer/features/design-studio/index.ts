// ── Main component ────────────────────────────────────────────────────────────
export { DesignStudio } from "./DesignStudio";
export { DesignProvider, useDesign } from "./stores/designStore";
export type { DesignState, DesignAction, Tool, CanvasPage, DesignProject } from "./types/canvas.types";

// ── Core: Commands ────────────────────────────────────────────────────────────
export type { Command } from "./core/commands/Command";
export { BaseCommand, CommandManager, commandManager } from "./core/commands";
export { AddObjectCommand }       from "./core/commands/commands/AddObject";
export { DeleteObjectCommand }    from "./core/commands/commands/DeleteObject";
export { MoveObjectCommand }      from "./core/commands/commands/MoveObject";
export { ResizeObjectCommand }    from "./core/commands/commands/ResizeObject";
export { RotateObjectCommand }    from "./core/commands/commands/RotateObject";
export { LockObjectCommand, UnlockObjectCommand } from "./core/commands/commands/LockObject";
export { ChangeColorCommand }     from "./core/commands/commands/ChangeColor";
export { ChangeFontCommand }      from "./core/commands/commands/ChangeFont";
export { DuplicateObjectCommand } from "./core/commands/commands/DuplicateObject";

// ── Core: Events ─────────────────────────────────────────────────────────────
export type { DesignEventMap, DesignEventName } from "./core/events/DesignEvents";
export { DesignEventBus, designBus } from "./core/events/DesignEventBus";

// ── Core: Tokens ─────────────────────────────────────────────────────────────
export type { DesignToken, TokenCategory } from "./core/tokens/DesignToken";
export { TokenRegistry, tokenRegistry } from "./core/tokens/TokenRegistry";
export { ALL_DEFAULT_TOKENS } from "./core/tokens/defaultTokens";

// ── Core: Plugins ─────────────────────────────────────────────────────────────
export type { Plugin, PluginContext } from "./core/plugins/PluginAPI";
export { PluginRegistry, pluginRegistry } from "./core/plugins/PluginRegistry";

// ── Core: Export / Import ─────────────────────────────────────────────────────
export type { ExportFormat, ExportRequest, ExportResult } from "./core/export/ExportPipeline";
export { ExportPipeline, exportPipeline } from "./core/export/ExportPipeline";
export type { Importer } from "./core/import/ImportPipeline";
export { ImportPipeline, importPipeline } from "./core/import/ImportPipeline";

// ── Core: Collaboration ───────────────────────────────────────────────────────
export type { CollaborationProvider, CollaboratorPresence, Comment } from "./core/collaboration/CollaborationTypes";
export { NoopCollaborationProvider } from "./core/collaboration/CollaborationTypes";

// ── Core: Performance ────────────────────────────────────────────────────────
export { ThumbnailCache, thumbnailCache } from "./core/performance/ThumbnailCache";
export { DebounceQueue, debounceQueue }   from "./core/performance/DebounceQueue";
export { ObjectPool }                     from "./core/performance/ObjectPool";

// ── Core: Layout ─────────────────────────────────────────────────────────────
export type { AutoLayoutConfig, ConstraintConfig } from "./core/layout/SmartLayout";
export { SmartLayoutEngine, smartLayout, defaultAutoLayout } from "./core/layout/SmartLayout";

// ── Features: Brand Kit ───────────────────────────────────────────────────────
export type { FullBrandKit } from "./features/brand-kit/BrandKit";
export { BrandKitService, brandKitService, makeDefaultBrandKit } from "./features/brand-kit";

// ── Features: Components ─────────────────────────────────────────────────────
export type { ComponentDefinition } from "./features/components/ComponentLibrary";
export { ComponentLibrary, componentLibrary, createComponent } from "./features/components/ComponentLibrary";
export { DEFAULT_COMPONENTS } from "./features/components/DefaultComponents";

// ── Features: AI ─────────────────────────────────────────────────────────────
export { AIDesignEngine, aiDesignEngine } from "./features/ai/AIDesignEngine";

// ── Features: Inspectors ─────────────────────────────────────────────────────
export { PositionInspector }   from "./features/properties/inspectors/PositionInspector";
export { TypographyInspector } from "./features/properties/inspectors/TypographyInspector";
export { AppearanceInspector } from "./features/properties/inspectors/AppearanceInspector";
export { ShadowInspector }     from "./features/properties/inspectors/ShadowInspector";
export { BorderInspector }     from "./features/properties/inspectors/BorderInspector";
export { EffectsInspector }    from "./features/properties/inspectors/EffectsInspector";
