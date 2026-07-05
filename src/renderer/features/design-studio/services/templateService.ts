import type { Template } from "../types/canvas.types";

// Built-in templates — page dimensions + blank Fabric JSON
const BUILT_IN: Template[] = [
  {
    id:          "tpl_blank_hd",
    name:        "Blank (16:9)",
    category:    "Basic",
    thumbnail:   "",
    width:       1280,
    height:      720,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["blank", "hd"],
    isPremium:   false,
  },
  {
    id:          "tpl_blank_sq",
    name:        "Blank Square",
    category:    "Basic",
    thumbnail:   "",
    width:       1000,
    height:      1000,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["blank", "square", "social"],
    isPremium:   false,
  },
  {
    id:          "tpl_blank_story",
    name:        "Story / Reel (9:16)",
    category:    "Social",
    thumbnail:   "",
    width:       1080,
    height:      1920,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["story", "instagram", "tiktok"],
    isPremium:   false,
  },
  {
    id:          "tpl_blank_a4",
    name:        "A4 Document",
    category:    "Print",
    thumbnail:   "",
    width:       2480,
    height:      3508,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["a4", "print", "document"],
    isPremium:   false,
  },
  {
    id:          "tpl_blank_present",
    name:        "Presentation (4:3)",
    category:    "Presentation",
    thumbnail:   "",
    width:       1024,
    height:      768,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["presentation", "slides"],
    isPremium:   false,
  },
  {
    id:          "tpl_blank_twitter",
    name:        "Twitter / X Banner",
    category:    "Social",
    thumbnail:   "",
    width:       1500,
    height:      500,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["twitter", "banner", "social"],
    isPremium:   false,
  },
  {
    id:          "tpl_blank_yt_thumb",
    name:        "YouTube Thumbnail",
    category:    "Social",
    thumbnail:   "",
    width:       1280,
    height:      720,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["youtube", "thumbnail"],
    isPremium:   false,
  },
  {
    id:          "tpl_blank_email",
    name:        "Email Header",
    category:    "Marketing",
    thumbnail:   "",
    width:       600,
    height:      200,
    json:        { version: "6.6.0", objects: [] },
    tags:        ["email", "marketing"],
    isPremium:   false,
  },
];

export function listTemplates(category?: string): Template[] {
  if (!category || category === "All") return BUILT_IN;
  return BUILT_IN.filter(t => t.category === category);
}

export function getTemplate(id: string): Template | undefined {
  return BUILT_IN.find(t => t.id === id);
}

export function searchTemplates(query: string): Template[] {
  const q = query.toLowerCase();
  return BUILT_IN.filter(
    t =>
      t.name.toLowerCase().includes(q) ||
      t.tags.some(tag => tag.includes(q)) ||
      t.category.toLowerCase().includes(q),
  );
}

export const TEMPLATE_CATEGORIES = ["All", "Basic", "Social", "Presentation", "Print", "Marketing"];
