/**
 * Unified Import Pipeline.
 * Accepts SVG, JSON, PNG, JPG files and adds them to the canvas.
 * Architecture is ready for PDF, Figma, and PSD importers.
 */
import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import { FabricImage, loadSVGFromString, util } from "fabric";
import { attachMeta } from "../../utils/fabricUtils";
import { uid } from "../../utils/geometryUtils";
import { designBus } from "../events/DesignEventBus";

// ── Importer interface ────────────────────────────────────────────────────────

export interface Importer {
  /** MIME types this importer handles */
  accepts: string[];
  label:   string;
  import(file: File, canvas: FabricCanvas): Promise<void>;
}

// ── Built-in importers ────────────────────────────────────────────────────────

const svgImporter: Importer = {
  accepts: ["image/svg+xml"],
  label:   "SVG",
  async import(file, canvas) {
    const text = await file.text();
    const { objects, options } = await loadSVGFromString(text);
    const group = util.groupSVGElements(objects as FabricObject[], options);
    const maxW  = (canvas.width  ?? 1280) * 0.6;
    const maxH  = (canvas.height ?? 720)  * 0.6;
    const scale = Math.min(maxW / (group.width ?? 1), maxH / (group.height ?? 1), 1);
    group.scale(scale);
    group.set({
      left: ((canvas.width  ?? 1280) - (group.width  ?? 0) * scale) / 2,
      top:  ((canvas.height ?? 720)  - (group.height ?? 0) * scale) / 2,
    });
    attachMeta(group, { id: uid(), name: file.name, type: "shape" });
    canvas.add(group);
    canvas.setActiveObject(group);
    canvas.renderAll();
  },
};

const imageImporter: Importer = {
  accepts: ["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"],
  label:   "Image",
  async import(file, canvas) {
    const dataUrl = await fileToDataUrl(file);
    const img     = await FabricImage.fromURL(dataUrl, { crossOrigin: "anonymous" });
    const maxW    = (canvas.width  ?? 1280) * 0.5;
    const maxH    = (canvas.height ?? 720)  * 0.5;
    const scale   = Math.min(maxW / (img.width ?? 1), maxH / (img.height ?? 1), 1);
    img.scale(scale);
    img.set({
      left: ((canvas.width  ?? 1280) - (img.width  ?? 0) * scale) / 2,
      top:  ((canvas.height ?? 720)  - (img.height ?? 0) * scale) / 2,
    });
    attachMeta(img, { id: uid(), name: file.name, type: "image" });
    canvas.add(img);
    canvas.setActiveObject(img);
    canvas.renderAll();
  },
};

const jsonImporter: Importer = {
  accepts: ["application/json"],
  label:   "JSON Design",
  async import(file, canvas) {
    const text = await file.text();
    const data = JSON.parse(text);
    // Supports both raw canvas JSON and project JSON
    const canvasJson = data.pages ? data.pages[0]?.json : data;
    if (!canvasJson) throw new Error("Invalid design JSON");
    await canvas.loadFromJSON(canvasJson as Parameters<typeof canvas.loadFromJSON>[0]);
    canvas.renderAll();
  },
};

// ── Pipeline ──────────────────────────────────────────────────────────────────

export class ImportPipeline {
  private readonly importers: Importer[] = [svgImporter, imageImporter, jsonImporter];

  /** Register a plugin importer */
  register(importer: Importer): void {
    this.importers.push(importer);
  }

  /** Import a file into the canvas */
  async import(file: File, canvas: FabricCanvas): Promise<void> {
    const importer = this.resolve(file);
    if (!importer) throw new Error(`No importer for MIME type: ${file.type}`);

    await importer.import(file, canvas);
    designBus.emit("AssetImported", {
      assetId: uid(),
      name:    file.name,
      type:    file.type,
    });
  }

  /** Import multiple files */
  async importAll(files: File[], canvas: FabricCanvas): Promise<void> {
    for (const file of files) {
      try {
        await this.import(file, canvas);
      } catch (err) {
        console.error(`[ImportPipeline] Failed to import "${file.name}":`, err);
      }
    }
  }

  /** Check if a file type is supported */
  supports(file: File): boolean {
    return !!this.resolve(file);
  }

  acceptedMimeTypes(): string[] {
    return this.importers.flatMap(i => i.accepts);
  }

  private resolve(file: File): Importer | undefined {
    return this.importers.find(i => i.accepts.includes(file.type));
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/** Module-level singleton */
export const importPipeline = new ImportPipeline();
