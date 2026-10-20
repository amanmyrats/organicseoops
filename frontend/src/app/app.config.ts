import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideClientHydration, withEventReplay, withNoHttpTransferCache } from '@angular/platform-browser';
import { provideRouter, withInMemoryScrolling } from '@angular/router';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withInMemoryScrolling({ scrollPositionRestoration: 'enabled', anchorScrolling: 'enabled' })),
    provideClientHydration(withEventReplay(), withNoHttpTransferCache()),
  ],
};
