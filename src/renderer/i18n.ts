import i18next from "i18next";
import { initReactI18next } from "react-i18next";

import commonEn from "./locales/en/common.json";
import commonAr from "./locales/ar/common.json";
import homeEn from "./locales/en/home.json";
import homeAr from "./locales/ar/home.json";
import settingsEn from "./locales/en/settings.json";
import settingsAr from "./locales/ar/settings.json";
import authEn from "./locales/en/auth.json";
import authAr from "./locales/ar/auth.json";
import socialEn from "./locales/en/social.json";
import socialAr from "./locales/ar/social.json";
import organizationsEn from "./locales/en/organizations.json";
import organizationsAr from "./locales/ar/organizations.json";
import sandboxEn from "./locales/en/sandbox.json";
import sandboxAr from "./locales/ar/sandbox.json";
import pluginsEn from "./locales/en/plugins.json";
import pluginsAr from "./locales/ar/plugins.json";
import automationEn from "./locales/en/automation.json";
import automationAr from "./locales/ar/automation.json";
import marketplaceEn from "./locales/en/marketplace.json";
import marketplaceAr from "./locales/ar/marketplace.json";
import aiRoutingEn from "./locales/en/aiRouting.json";
import aiRoutingAr from "./locales/ar/aiRouting.json";
import observabilityEn from "./locales/en/observability.json";
import observabilityAr from "./locales/ar/observability.json";
import aiEn from "./locales/en/ai.json";
import aiAr from "./locales/ar/ai.json";
import designStudioEn from "./locales/en/designStudio.json";
import designStudioAr from "./locales/ar/designStudio.json";
import teamsEn from "./locales/en/teams.json";
import teamsAr from "./locales/ar/teams.json";
import billingEn from "./locales/en/billing.json";
import billingAr from "./locales/ar/billing.json";
import agentosEn from "./locales/en/agentos.json";
import agentosAr from "./locales/ar/agentos.json";
import devEn from "./locales/en/dev.json";
import devAr from "./locales/ar/dev.json";
import integrationsEn from "./locales/en/integrations.json";
import integrationsAr from "./locales/ar/integrations.json";

void i18next.use(initReactI18next).init({
  resources: {
    en: {
      common: commonEn, home: homeEn, settings: settingsEn, auth: authEn, social: socialEn,
      organizations: organizationsEn, sandbox: sandboxEn, plugins: pluginsEn, automation: automationEn,
      marketplace: marketplaceEn, aiRouting: aiRoutingEn, observability: observabilityEn, ai: aiEn,
      designStudio: designStudioEn, teams: teamsEn, billing: billingEn, agentos: agentosEn, dev: devEn,
      integrations: integrationsEn,
    },
    ar: {
      common: commonAr, home: homeAr, settings: settingsAr, auth: authAr, social: socialAr,
      organizations: organizationsAr, sandbox: sandboxAr, plugins: pluginsAr, automation: automationAr,
      marketplace: marketplaceAr, aiRouting: aiRoutingAr, observability: observabilityAr, ai: aiAr,
      designStudio: designStudioAr, teams: teamsAr, billing: billingAr, agentos: agentosAr, dev: devAr,
      integrations: integrationsAr,
    },
  },
  lng: "en",
  fallbackLng: "en",
  defaultNS: "common",
  ns: [
    "common", "home", "settings", "auth", "social", "organizations", "sandbox", "plugins",
    "automation", "marketplace", "aiRouting", "observability", "ai", "designStudio", "teams", "billing", "agentos", "dev",
    "integrations",
  ],
  interpolation: { escapeValue: false },
  returnEmptyString: false,
});

export default i18next;
