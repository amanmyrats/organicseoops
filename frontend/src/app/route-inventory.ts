// Build-time inventory, also consumed by the static-output check.
// These are development routes, not the final public page/keyword map.
export const publicPaths = ['', 'preview', 'preview/tr', 'sample-report', 'preview/tr/sample-report', 'preview/tr/home', 'preview/tr/404', '404', 'preview/help', 'preview/tr/help', 'preview/data-sources', 'preview/tr/data-sources', 'preview/technical-seo-audits', 'preview/tr/technical-seo-audits', 'preview/seo-agencies', 'preview/tr/seo-agencies', 'preview/airport-transfer-seo', 'preview/tr/airport-transfer-seo', 'preview/seo-opportunities', 'preview/tr/seo-opportunities', 'preview/content-and-keywords', 'preview/tr/content-and-keywords', 'preview/pricing', 'preview/tr/pricing', 'preview/contact', 'preview/tr/contact', 'preview/accessibility', 'preview/tr/accessibility', 'preview/data-handling', 'preview/tr/data-handling', 'preview/cancellation', 'preview/tr/cancellation', 'preview/privacy', 'preview/tr/privacy', 'preview/terms', 'preview/tr/terms'] as const;
export const clientPrefixes = ['account', 'app'] as const;

// Candidate identifiers only; canonical publication approvals still gate use.
export const publicAnalyticsRoutes = [
  { path: '', id: 'HOME', locale: 'en', ctaIds: ['public_trial_cta'] },
  { path: 'sample-report', id: 'SAMPLE', locale: 'en', ctaIds: [] },
] as const;
