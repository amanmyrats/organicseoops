import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: 'account', loadChildren: () => import('./account/account.routes').then((m) => m.accountRoutes) },
  { path: 'app', loadChildren: () => import('./workspace/workspace.routes').then((m) => m.workspaceRoutes) },
  { path: '', loadChildren: () => import('./public/public.routes').then((m) => m.publicRoutes) },
];
