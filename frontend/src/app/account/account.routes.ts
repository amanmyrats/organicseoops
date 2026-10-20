import { Routes } from '@angular/router';

export const accountRoutes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'login' },
  { path: 'login', title: 'Sign in — OrganicSEOOps', loadComponent: () => import('./login').then((m) => m.Login) },
  { path: 'register', title: 'Create account — OrganicSEOOps', loadComponent: () => import('./register').then((m) => m.Register) },
  { path: 'forgot-password', title: 'Reset password — OrganicSEOOps', loadComponent: () => import('./forgot-password').then((m) => m.ForgotPassword) },
  { path: 'reset-password', title: 'Choose new password — OrganicSEOOps', loadComponent: () => import('./reset-password').then((m) => m.ResetPassword) },
  { path: 'security', title: 'Security and sessions — OrganicSEOOps', loadComponent: () => import('./security').then((m) => m.Security) },
  { path: 'provider-settings', title: 'Provider credentials — OrganicSEOOps', loadComponent: () => import('./provider-settings').then((m) => m.ProviderSettings) },
  { path: 'acquisition', title: 'Operational acquisition milestones — OrganicSEOOps', loadComponent: () => import('./acquisition').then((m) => m.Acquisition) },
  { path: 'billing/checkout', title: 'Hosted checkout — OrganicSEOOps', loadComponent: () => import('./checkout-page').then((m) => m.CheckoutPage) },
  { path: 'invitation', title: 'Organization invitation — OrganicSEOOps', loadComponent: () => import('./invitation').then((m) => m.Invitation) },
  { path: 'verify', title: 'Verify email — OrganicSEOOps', loadComponent: () => import('./verification-pending').then((m) => m.VerificationPending) },
  { path: 'verify-email', title: 'Verify email — OrganicSEOOps', loadComponent: () => import('./verify-email').then((m) => m.VerifyEmail) },
];
