// Public browser configuration only. Backend secrets belong in backend/.env.
export const environment = {
  production: false,
  apiBase: '/api',
  authBase: '/_allauth/browser/v1',
} as const;
