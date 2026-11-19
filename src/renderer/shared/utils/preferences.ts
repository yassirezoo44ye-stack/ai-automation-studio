/** Browser preferences shared by settings and the requests they control. */
export const CHAT_MODELS = ["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"] as const;
export const BUILD_MODELS = ["claude-sonnet-4-6", "claude-opus-4-8"] as const;
export interface UserPrefs {
  chatModel: string;
  buildModel: string;
  sidebarMode: "expanded" | "collapsed";
}
const PREFS_KEY = "axon-prefs";
const DEFAULT_PREFS: UserPrefs = { chatModel: CHAT_MODELS[0], buildModel: BUILD_MODELS[0], sidebarMode: "expanded" };
export function loadPrefs(): UserPrefs {
  try {
    const value = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}");
    return {
      chatModel: CHAT_MODELS.includes(value?.chatModel) ? value.chatModel : DEFAULT_PREFS.chatModel,
      buildModel: BUILD_MODELS.includes(value?.buildModel) ? value.buildModel : DEFAULT_PREFS.buildModel,
      sidebarMode: value?.sidebarMode === "collapsed" ? "collapsed" : "expanded",
    };
  } catch { return { ...DEFAULT_PREFS }; }
}
/** Throws when the browser cannot persist preferences, so the UI cannot claim a save. */
export function savePrefs(prefs: UserPrefs): void {
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
}
