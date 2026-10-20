import { RenderMode, ServerRoute } from '@angular/ssr';
import { clientPrefixes, publicPaths } from './route-inventory';

export const serverRoutes: ServerRoute[] = [
  ...publicPaths.map<ServerRoute>((path) => ({ path, renderMode: RenderMode.Prerender })),
  ...clientPrefixes.flatMap<ServerRoute>((path) => [
    { path, renderMode: RenderMode.Client },
    { path: `${path}/**`, renderMode: RenderMode.Client },
  ]),
  // Client-side navigation can show NotFound. Static hosts must return a real
  // 404 for unknown public requests, never rewrite them to the CSR entry.
  { path: '**', renderMode: RenderMode.Client },
];
