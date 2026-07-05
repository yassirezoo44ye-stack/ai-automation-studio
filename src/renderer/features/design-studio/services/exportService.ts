import type { Canvas as FabricCanvas } from "fabric";
import type { DesignProject } from "../types/canvas.types";

export type ExportFormat = "png" | "jpg" | "svg" | "json";

export interface ExportOptions {
  format:     ExportFormat;
  quality?:   number; // 0–1 for jpg
  multiplier?: number; // resolution scale (default 1)
  pageId?:    string;
}

// ── Canvas export ──────────────────────────────────────────────────────────────

export function exportCanvas(
  canvas: FabricCanvas,
  opts: ExportOptions,
): void {
  const { format, quality = 0.92, multiplier = 2 } = opts;

  if (format === "json") {
    const json = JSON.stringify(canvas.toObject(["_meta"]), null, 2);
    downloadBlob(new Blob([json], { type: "application/json" }), "design.json");
    return;
  }

  if (format === "svg") {
    const svg = canvas.toSVG();
    downloadBlob(new Blob([svg], { type: "image/svg+xml" }), "design.svg");
    return;
  }

  const mime = format === "jpg" ? "image/jpeg" : "image/png";
  const dataUrl = canvas.toDataURL({
    format:     format === "jpg" ? "jpeg" : "png",
    quality,
    multiplier,
  });

  downloadDataUrl(dataUrl, `design.${format}`, mime);
}

// ── Project export ─────────────────────────────────────────────────────────────

export function exportProjectJSON(project: DesignProject): void {
  const json = JSON.stringify(project, null, 2);
  downloadBlob(
    new Blob([json], { type: "application/json" }),
    `${project.name.replace(/\s+/g, "_")}.axon.json`,
  );
}

// ── Download helpers ───────────────────────────────────────────────────────────

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  downloadDataUrl(url, filename);
  URL.revokeObjectURL(url);
}

function downloadDataUrl(url: string, filename: string, _mime?: string): void {
  const a  = document.createElement("a");
  a.href   = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ── Print ──────────────────────────────────────────────────────────────────────

export function printCanvas(canvas: FabricCanvas): void {
  const dataUrl = canvas.toDataURL({ multiplier: 2, format: "png" });
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(
    `<html><body style="margin:0"><img src="${dataUrl}" style="max-width:100%"/></body></html>`
  );
  win.document.close();
  win.focus();
  win.print();
  win.close();
}
