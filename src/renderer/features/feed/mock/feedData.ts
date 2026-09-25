import type { FeedItem } from "../types/feed.types";

/**
 * Phase 1 mock feed — 12 realistic items covering all content types.
 * Each item uses a unique gradient so the feed looks visually diverse.
 * Replace this array with an API call in Phase 2 without touching any component.
 */
export const MOCK_FEED: FeedItem[] = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    type: "AGENT",
    creator: { id: "u1", name: "Ahmed K.", handle: "@ahmedk.dev" },
    title: "AI Sales Agent",
    description:
      "وكيل ذكاء اصطناعي يتواصل مع العملاء المحتملين، يؤهّلهم تلقائياً ويرسل عروضاً مخصصة — كلّ ذلك بدون تدخل بشري.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #0d0020 0%, #3b0764 40%, #6E32E0 75%, #0B7A70 100%)",
    },
    tags: ["AI", "Sales", "Agents"],
    likes: 4821, comments: 312, shares: 891, saves: 1203,
    ctaType: "build-agent",
    targetPage: "agentos",
    sourceId: "tpl-sales-agent-v2",
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    type: "AUTOMATION",
    creator: { id: "u2", name: "Sara M.", handle: "@saraflow" },
    title: "WhatsApp Lead Automation",
    description:
      "كل رسالة جديدة على واتساب تُضاف تلقائياً إلى CRM وتُرسل رداً فورياً مخصصاً — بدون أي سطر كود.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #052e16 0%, #065f46 45%, #10b981 85%, #34d399 100%)",
    },
    tags: ["WhatsApp", "Automation", "CRM"],
    likes: 7341, comments: 541, shares: 1230, saves: 2100,
    ctaType: "use-automation",
    targetPage: "automation",
    sourceId: "auto-whatsapp-crm",
  },
  {
    id: "00000000-0000-4000-8000-000000000003",
    type: "APP",
    creator: { id: "u3", name: "Omar T.", handle: "@omartariq" },
    title: "SaaS Dashboard Builder",
    description:
      "اصنع لوحة تحكم SaaS كاملة في دقائق — رسوم بيانية، جداول، مستخدمين، وخطط اشتراك — كلّها مُدمجة وجاهزة للإطلاق.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #0c1445 0%, #1e3a8a 40%, #3b82f6 75%, #60a5fa 100%)",
    },
    tags: ["SaaS", "Dashboard", "App Builder"],
    likes: 9124, comments: 874, shares: 2011, saves: 3400,
    ctaType: "build-app",
    targetPage: "app-builder",
    sourceId: "tpl-saas-dashboard",
  },
  {
    id: "00000000-0000-4000-8000-000000000004",
    type: "AGENT",
    creator: { id: "u4", name: "Lina A.", handle: "@linaauto" },
    title: "AI Customer Support",
    description:
      "وكيل دعم يحل 80٪ من استفسارات العملاء تلقائياً، يُصعّد الحالات المعقدة فقط إلى فريق الدعم البشري.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #083344 0%, #164e63 40%, #0891b2 75%, #22d3ee 100%)",
    },
    tags: ["Support", "AI", "Agents"],
    likes: 5633, comments: 401, shares: 998, saves: 1890,
    ctaType: "build-agent",
    targetPage: "agentos",
    sourceId: "tpl-support-agent",
  },
  {
    id: "00000000-0000-4000-8000-000000000005",
    type: "APP",
    creator: { id: "u5", name: "Nora S.", handle: "@norabuilds" },
    title: "Website Generator",
    description:
      "صِف موقعك بالعربية أو الإنجليزية وسيُنشئ Flow موقعاً كاملاً بالتصميم والكود في أقل من دقيقة.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #3b0020 0%, #7c1d4e 45%, #db2777 80%, #f472b6 100%)",
    },
    tags: ["Website", "Generator", "No-code"],
    likes: 11203, comments: 943, shares: 3120, saves: 4500,
    ctaType: "build-app",
    targetPage: "app-builder",
    sourceId: "tpl-website-gen",
  },
  {
    id: "00000000-0000-4000-8000-000000000006",
    type: "AUTOMATION",
    creator: { id: "u6", name: "Faris H.", handle: "@farisdev" },
    title: "Invoice Automation",
    description:
      "أرسل الفواتير وتتبّع المدفوعات تلقائياً — تنبيهات بالتأخير، تقارير شهرية، وتكامل مباشر مع نظام المحاسبة.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #431407 0%, #9a3412 45%, #ea580c 80%, #fb923c 100%)",
    },
    tags: ["Finance", "Automation", "Invoices"],
    likes: 3892, comments: 227, shares: 601, saves: 988,
    ctaType: "use-automation",
    targetPage: "automation",
    sourceId: "auto-invoice-flow",
  },
  {
    id: "00000000-0000-4000-8000-000000000007",
    type: "APP",
    creator: { id: "u7", name: "Dev X.", handle: "@devxflow" },
    title: "Python API Builder",
    description:
      "أنشئ API بـ FastAPI في ثوانٍ — مسارات، مصادقة، قاعدة بيانات، وتوثيق تلقائي. منتشر ويعمل فوراً.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #0f172a 0%, #1e293b 40%, #334155 70%, #475569 100%)",
    },
    tags: ["Python", "API", "Backend"],
    likes: 6210, comments: 488, shares: 1340, saves: 2200,
    ctaType: "build-app",
    targetPage: "app-builder",
    sourceId: "tpl-python-api",
  },
  {
    id: "00000000-0000-4000-8000-000000000008",
    type: "AGENT",
    creator: { id: "u8", name: "Rania Z.", handle: "@raniaai" },
    title: "AI Research Agent",
    description:
      "أعطه سؤالاً فيبحث في عشرات المصادر، يلخّص النتائج، ويُنشئ تقريراً منظّماً جاهزاً للمشاركة.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #1e1b4b 0%, #3730a3 45%, #6366f1 80%, #a5b4fc 100%)",
    },
    tags: ["Research", "AI", "Reports"],
    likes: 8934, comments: 712, shares: 1890, saves: 3100,
    ctaType: "build-agent",
    targetPage: "agentos",
    sourceId: "tpl-research-agent",
  },
  {
    id: "00000000-0000-4000-8000-000000000009",
    type: "AUTOMATION",
    creator: { id: "u9", name: "Khalid M.", handle: "@khalidauto" },
    title: "Social Media Automation",
    description:
      "جدوِل محتواك على تويتر وإنستغرام ولينكدإن تلقائياً — تحليل الأداء، اقتراح أفضل أوقات النشر، وإعادة نشر المحتوى الرابح.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #2d0036 0%, #7e22ce 45%, #c026d3 75%, #f0abfc 100%)",
    },
    tags: ["Social", "Automation", "Marketing"],
    likes: 13400, comments: 1102, shares: 4300, saves: 5800,
    ctaType: "use-automation",
    targetPage: "automation",
    sourceId: "auto-social-publisher",
  },
  {
    id: "00000000-0000-4000-8000-000000000010",
    type: "WORKFLOW",
    creator: { id: "u10", name: "Hala B.", handle: "@halabuilds" },
    title: "CRM Workflow",
    description:
      "سير عمل يجمع بين جذب العملاء، تتبّع المبيعات، وإرسال رسائل المتابعة — كل شيء مترابط ومُتزامن.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #022c22 0%, #065f46 45%, #0d9488 80%, #2dd4bf 100%)",
    },
    tags: ["CRM", "Workflow", "Sales"],
    likes: 4102, comments: 298, shares: 720, saves: 1400,
    ctaType: "run-workflow",
    targetPage: "automation",
    sourceId: "wf-crm-pipeline",
  },
  {
    id: "00000000-0000-4000-8000-000000000011",
    type: "TEMPLATE",
    creator: { id: "u11", name: "Youssef A.", handle: "@youssefux" },
    title: "Landing Page Builder",
    description:
      "قالب احترافي لصفحة هبوط مع نموذج تسجيل، عرض الميزات، وشهادات العملاء — قابل للتخصيص الكامل.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #431407 0%, #b45309 45%, #d97706 75%, #fbbf24 100%)",
    },
    tags: ["Landing Page", "Template", "Marketing"],
    likes: 7823, comments: 564, shares: 1890, saves: 2900,
    ctaType: "use-template",
    targetPage: "marketplace",
    sourceId: "tpl-landing-v3",
  },
  {
    id: "00000000-0000-4000-8000-000000000012",
    type: "AGENT",
    creator: { id: "u12", name: "Mona R.", handle: "@monaanalytics" },
    title: "Business Analytics Agent",
    description:
      "وكيل يحلّل بياناتك، يُنشئ تقارير مرئية تفاعلية، ويُجيب على أسئلتك بلغة طبيعية — بدون SQL أو Excel.",
    media: {
      type: "gradient",
      gradient:
        "linear-gradient(150deg, #0a0a0a 0%, #18181b 35%, #27272a 60%, #3f3f46 100%)",
    },
    tags: ["Analytics", "Business", "AI"],
    likes: 6712, comments: 503, shares: 1120, saves: 2400,
    ctaType: "build-agent",
    targetPage: "agentos",
    sourceId: "tpl-analytics-agent",
  },
];
