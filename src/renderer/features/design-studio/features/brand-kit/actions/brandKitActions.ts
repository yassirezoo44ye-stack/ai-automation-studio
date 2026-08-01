/**
 * BrandKit Actions — the Command API between UI intent and BrandKitService.
 *
 * Each action normalizes UI input (trim, title-case, deriving domain fields
 * like `name` from `family`) and delegates to BrandKitService. Domain
 * validation (non-empty, hex format, data-URL format) lives in
 * BrandKitService itself, not here — so those rules hold for any caller,
 * not just this Command API. No persistence logic lives here — that stays
 * in BrandKitService/BrandKitRepository — and no action touches designStore
 * or React directly; the loop back to the UI closes through the
 * BrandKitChanged event useBrandKit() already subscribes to (Phase A),
 * regardless of which action triggered it.
 *
 * Scoped to exactly what BrandKitPanel does today: add/remove for
 * colors, fonts, and logos. BrandKitService's kit-lifecycle methods
 * (setActive/create/duplicate/delete) stay available but unwrapped here —
 * there's no UI path for switching between kits yet, so an Actions
 * wrapper for them would have no caller (see Commit 4).
 */
import type { BrandColor, BrandLogo, FullBrandKit } from "../BrandKit";
import { brandKitService } from "../BrandKitService";

// ── Normalization helpers ───────────────────────────────────────────────────

function titleCase(value: string): string {
  return value.replace(/\w\S*/g, word => word[0].toUpperCase() + word.slice(1).toLowerCase());
}

// ── Colors ───────────────────────────────────────────────────────────────────

export interface AddColorInput {
  name: string;
  value: string;
  shade?: BrandColor["shade"];
}

async function addColor(input: AddColorInput): Promise<FullBrandKit> {
  return brandKitService.addColor({ name: input.name.trim(), value: input.value.trim(), shade: input.shade });
}

async function removeColor(id: string): Promise<FullBrandKit> {
  return brandKitService.removeColor(id.trim());
}

// ── Fonts ────────────────────────────────────────────────────────────────────

export interface AddFontInput {
  family: string;
  weights?: number[];
}

async function addFont(input: AddFontInput): Promise<FullBrandKit> {
  const family = titleCase(input.family.trim());
  const name = family.split(",")[0].trim();
  const weights = input.weights?.length ? input.weights : [400, 700];
  return brandKitService.addFont({ name, family, weights });
}

async function removeFont(id: string): Promise<FullBrandKit> {
  return brandKitService.removeFont(id.trim());
}

// ── Logos ────────────────────────────────────────────────────────────────────

export interface AddLogoInput {
  name: string;
  src: string;
  variant?: BrandLogo["variant"];
}

async function addLogo(input: AddLogoInput): Promise<FullBrandKit> {
  return brandKitService.addLogo({ name: input.name.trim(), src: input.src.trim(), variant: input.variant });
}

async function removeLogo(id: string): Promise<FullBrandKit> {
  return brandKitService.removeLogo(id.trim());
}

// ── Command API ──────────────────────────────────────────────────────────────

export const brandKitActions = {
  addColor,
  removeColor,
  addFont,
  removeFont,
  addLogo,
  removeLogo,
};
