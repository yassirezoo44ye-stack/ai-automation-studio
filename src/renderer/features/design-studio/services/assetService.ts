import type { Asset, AssetType } from "../types/canvas.types";
import { uid } from "../utils/geometryUtils";

const DB_NAME    = "axon_design_assets";
const DB_VERSION = 1;
const STORE_NAME = "assets";

// ── IndexedDB helpers ──────────────────────────────────────────────────────────

let _db: IDBDatabase | null = null;

async function openDB(): Promise<IDBDatabase> {
  if (_db) return _db;
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = (e.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("type",       "type",       { unique: false });
        store.createIndex("uploadedAt", "uploadedAt", { unique: false });
      }
    };
    req.onsuccess = () => { _db = req.result; resolve(_db); };
    req.onerror   = () => reject(req.error);
  });
}

function tx(db: IDBDatabase, mode: IDBTransactionMode) {
  return db.transaction(STORE_NAME, mode).objectStore(STORE_NAME);
}

function promisify<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((res, rej) => {
    req.onsuccess = () => res(req.result);
    req.onerror   = () => rej(req.error);
  });
}

// ── Asset CRUD ─────────────────────────────────────────────────────────────────

export async function listAssets(type?: AssetType): Promise<Asset[]> {
  const db    = await openDB();
  const store = tx(db, "readonly");
  const all   = await promisify<Asset[]>(store.getAll());
  if (!type) return all.sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
  return all.filter(a => a.type === type).sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
}

export async function getAsset(id: string): Promise<Asset | undefined> {
  const db = await openDB();
  return promisify(tx(db, "readonly").get(id));
}

export async function saveAsset(
  file: File,
  type: AssetType,
): Promise<Asset> {
  const db = await openDB();

  const dataUrl = await fileToDataUrl(file);
  const asset: Asset = {
    id:         uid(),
    name:       file.name,
    type,
    src:        dataUrl,
    size:       file.size,
    mimeType:   file.type,
    uploadedAt: new Date().toISOString(),
    isFavorite: false,
  };

  await promisify(tx(db, "readwrite").put(asset));
  return asset;
}

export async function deleteAsset(id: string): Promise<void> {
  const db = await openDB();
  await promisify(tx(db, "readwrite").delete(id));
}

export async function toggleAssetFavorite(id: string): Promise<Asset | undefined> {
  const db    = await openDB();
  const store = tx(db, "readwrite");
  const asset = await promisify<Asset>(store.get(id));
  if (!asset) return undefined;
  const updated = { ...asset, isFavorite: !asset.isFavorite };
  await promisify(store.put(updated));
  return updated;
}

export async function searchAssets(query: string): Promise<Asset[]> {
  const all = await listAssets();
  const q   = query.toLowerCase();
  return all.filter(a => a.name.toLowerCase().includes(q));
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function inferAssetType(file: File): AssetType {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  if (file.type === "application/pdf") return "pdf";
  if (file.type === "image/svg+xml")   return "svg";
  return "image";
}
