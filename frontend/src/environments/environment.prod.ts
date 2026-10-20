// Public build-time configuration. Production serves API/auth on the same origin.
export const environment = {
  production: true,
  apiBase: '/api',
  authBase: '/_allauth/browser/v1',
} as const;
