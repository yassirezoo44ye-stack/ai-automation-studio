import i18n from "../../i18n";
import type { Lang } from "../../contexts/lang";

export function relTime(iso: string, lang: Lang = "en"): string {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return i18n.t("common:time.justNow", { lng: lang });
  if (s < 3600) return i18n.t("common:time.minutesAgo", { count: Math.floor(s / 60), lng: lang });
  if (s < 86400) return i18n.t("common:time.hoursAgo", { count: Math.floor(s / 3600), lng: lang });
  return new Date(iso).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US");
}

export function formatDate(iso: string, lang: Lang = "en"): string {
  return new Date(iso).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US");
}
