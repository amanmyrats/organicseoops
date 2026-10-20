# Frontend foundation

Angular public pages are prerendered; account/app pages are lazy-loaded CSR. Local routes implement cookie-session account flows, server-fed organization/project context, team/role administration, fragment-token invitation acceptance, ownership transfer and suspension states, and a development-only cost-free diagnostic jobs page with scoped polling/partial evidence and paused-first schedules. Production email delivery, real customer job handlers and a public offer are not available. All preview routes are deliberately `noindex`. Final copy, launch routes, canonicals and localization await their product decisions.

## Run and verify

The reproducible target is Node 24.21.0 (`.nvmrc`) and npm 11.19.0 (D049). Compatible Node 24.15+ and npm 11.13+ within those major lines also support local development. From `frontend/`:

```sh
npm ci  # initial install or dependency/lockfile change
npm start
```

During coding, run selected specs with `npm test -- --include=app/PATH.spec.ts` (path relative to `src/`); choose the actual affected spec. `npm run check` runs the full suite, production build and static checks together and belongs to explicitly selected final validation under AGENTS.md D423/D425. Reuse unchanged passing evidence; no full check or reinstall is needed just to start/resume development.

For API-backed browser work, inspect `../backend-dev.sh status` once and reuse
healthy backend services; use `setup` only for initial setup or `up` once for
missing/stopped required services. Frontend source/type/spec checks do not need
backend startup. The Angular development server proxies `/api` and
`/_allauth` to `http://127.0.0.1:18000`; browser requests therefore remain
same-origin at `http://127.0.0.1:4200` for session cookies and CSRF. Production
build output is unaffected by this development-only proxy.

## Environment selection

- `src/environments/environment.ts`: local development (`npm start` or `npx ng serve`).
- `src/environments/environment.prod.ts`: production (`npm run build`); Angular's
  production `fileReplacements` selects it automatically.
- API clients import `environment`, using its `apiBase` and `authBase`. Both builds
  keep same-origin relative paths for cookies/CSRF; production hosting must route
  these paths to Django. `proxy.conf.json` targets only the local backend.

These TypeScript files are versioned public browser configuration, not secret
stores. Angular does not load backend `.env` files or require a frontend dotenv
file. Backend credentials belong exclusively in `backend/.env` / `.env.prod`.

Select the target runtimes with your existing version manager for reproducible CI-equivalent checks. The checkpoint records the actual runtime used by each verification; a compatible local run is not evidence of a run on a different version.

P04-05 passed26 Angular interaction/route tests and the production/static build
on the compatible local Node runtime; P02-04's earlier exact-target fresh-install
and audit evidence remains in the checkpoint. An exact-target P04-05 rerun is not claimed.
The check-only workflow and failure-propagation evidence are described
in the [CI guide](../deploy/checks/README.md).

`check` runs router tests, the production build (including strict Angular/TypeScript checks and asset budgets), and assertions against generated static HTML. Only `dist/organicseoops/browser/` is a deployment artifact. There is no production Node entry point. The four current English routes include a noindex **synthetic** `/sample-report`; none are approved marketing pages or translated. `publication-approvals.json` contains draft states only, and the separate release guard intentionally fails before any public upload; see [content review and rollback](../docs/PUBLIC_CONTENT_WORKFLOW.md).

## Static route contract

The build inventory is `src/app/route-inventory.ts`; Angular rendering modes live in `app.routes.server.ts`.

| Request | Static hosting behavior required |
| --- | --- |
| `/` | Serve `index.html` |
| `/preview` | Serve `preview/index.html` |
| Unknown public URL | Return HTTP 404 with `404/index.html`; never blanket-rewrite to CSR |
| `/account`, `/account/*`, `/app`, `/app/*` | Serve `index.csr.html` for extensionless application routes |
| Missing asset | Return HTTP 404; never serve an HTML app shell |

These are hosting requirements, not an assertion that CloudFront is configured. P13-02 verifies deployed HTTP statuses, redirects and cache behavior. Angular's development server is not the production routing contract. The router separately shows a not-found component for unknown client-side navigation.

Public components use native semantic HTML and component-scoped CSS. Account/workspace code is lazy-loaded and no UI framework is installed. The provisional preview remains English; D092-D094 select English/Turkish launch coverage and review rules, but localization implementation and approved translations remain pending.
