/**
 * Unified Export Pipeline.
 * All formats go through ExportPipeline.run().
 * Plugins can add new formats via PluginRegistry.addExporter().
 */
import type { Canvas as FabricCanvas } from "fabric";
import type { DesignProject } from "../../types/canvas.types";
import { designBus } from "../events/DesignEventBus";

// ── Supported formats ─────────────────────────────────────────────────────────

export type ExportFormat = "png" | "jpg" | "svg" | "json" | "html" | "zip" | "pdf";

export interface ExportRequest {
  format:      ExportFormat;
  canvas:      FabricCanvas;
  project?:    DesignProject;
  pageIds?:    string[];
  filename?:   string;
  quality?:    number;    // 0–1 for jpg
  multiplier?: number;    // resolution scale
}

export interface ExportResult {
  blob:      Blob;
  filename:  string;
  format:    ExportFormat;
  bytes:     number;
}

// ── Exporter interface ────────────────────────────────────────────────────────

export interface Exporter {
  format:    ExportFormat;
  mimeType:  string;
  extension: string;
  export(req: ExportRequest): Blob | Promise<Blob>;
}

// ── Built-in exporters ────────────────────────────────────────────────────────

const pngExporter: Exporter = {
  format: "png", mimeType: "image/png", extension: "png",
  export({ canvas, multiplier = 2 }) {
    const dataUrl = canvas.toDataURL({ format: "png", multiplier });
    return dataUrlToBlob(dataUrl, "image/png");
  },
};

const jpgExporter: Exporter = {
  format: "jpg", mimeType: "image/jpeg", extension: "jpg",
  export({ canvas, quality = 0.92, multiplier = 2 }) {
    const dataUrl = canvas.toDataURL({ format: "jpeg", quality, multiplier });
    return dataUrlToBlob(dataUrl, "image/jpeg");
  },
};

const svgExporter: Exporter = {
  format: "svg", mimeType: "image/svg+xml", extension: "svg",
  export({ canvas }) {
    const svg = canvas.toSVG();
    return new Blob([svg], { type: "image/svg+xml" });
  },
};

const jsonExporter: Exporter = {
  format: "json", mimeType: "application/json", extension: "json",
  export({ canvas, project }) {
    const data = project ? project : canvas.toObject(["_meta"]);
    return new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  },
};

const htmlExporter: Exporter = {
  format: "html", mimeType: "text/html", extension: "html",
  export({ canvas }) {
    const dataUrl = canvas.toDataURL({ format: "png", multiplier: 1 });
    const html = `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Design Export</title>
<style>body{margin:0;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#FFFFFF;}img{max-width:100%;height:auto;}</style>
</head>
<body><img src="${dataUrl}" alt="Design export"/></body>
</html>`;
    return new Blob([html], { type: "text/html" });
  },
};

/** PDF uses print dialog (no server needed) */
const pdfExporter: Exporter = {
  format: "pdf", mimeType: "application/pdf", extension: "pdf",
  export({ canvas }) {
    const dataUrl = canvas.toDataURL({ multiplier: 2, format: "png" });
    const win = window.open("", "_blank");
    if (win) {
      win.document.write(
        `<html><body style="margin:0"><img src="${dataUrl}" style="max-width:100%"/></body></html>`
      );
      win.document.close();
      win.print();
    }
    // Return minimal blob for consistency
    return new Blob([dataUrl], { type: "text/plain" });
  },
};

/** ZIP bundles all pages; requires multiple canvas JSON states */
const zipExporter: Exporter = {
  format: "zip", mimeType: "application/zip", extension: "zip",
  export({ canvas, project }) {
    // Without JSZip we bundle as a JSON manifest
    const data = {
      exportedAt: new Date().toISOString(),
      pages: project ? project.pages.map(p => ({ id: p.id, name: p.name, json: p.json })) : [],
      currentCanvas: canvas.toObject(["_meta"]),
    };
    return new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  },
};

// ── Pipeline ──────────────────────────────────────────────────────────────────

export class ExportPipeline {
  private readonly exporters = new Map<ExportFormat, Exporter>([
    ["png",  pngExporter],
    ["jpg",  jpgExporter],
    ["svg",  svgExporter],
    ["json", jsonExporter],
    ["html", htmlExporter],
    ["pdf",  pdfExporter],
    ["zip",  zipExporter],
  ]);

  /** Register a plugin exporter (overrides built-in if same format) */
  register(exporter: Exporter): void {
    this.exporters.set(exporter.format, exporter);
  }

  async run(req: ExportRequest): Promise<ExportResult> {
    const exporter = this.exporters.get(req.format);
    if (!exporter) throw new Error(`Unsupported export format: ${req.format}`);

    const pageIds = req.pageIds ?? (req.project?.pages.map(p => p.id) ?? []);

    designBus.emit("ExportStarted", { format: req.format, pageIds });

    try {
      const blob = await exporter.export(req);
      const filename = req.filename ?? buildFilename(req.project?.name ?? "design", exporter.extension);

      designBus.emit("ExportFinished", { format: req.format, filename, bytes: blob.size });

      triggerDownload(blob, filename);

      return { blob, filename, format: req.format, bytes: blob.size };
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      designBus.emit("ExportFailed", { format: req.format, error });
      throw err;
    }
  }

  supportedFormats(): ExportFormat[] {
    return [...this.exporters.keys()];
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function dataUrlToBlob(dataUrl: string, mimeType: string): Blob {
  const [, b64] = dataUrl.split(",");
  const bytes   = atob(b64);
  const arr     = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mimeType });
}

function buildFilename(name: string, ext: string): string {
  return `${name.replace(/\s+/g, "_")}.${ext}`;
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href    = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Module-level singleton */
export const exportPipeline = new ExportPipeline();
