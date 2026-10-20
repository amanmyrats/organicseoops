import { DOCUMENT } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { AnalyticsPreferences } from './analytics-preferences';

@Component({
  selector: 'app-root',
  imports: [RouterLink, RouterOutlet, AnalyticsPreferences],
  template: `
    <a class="skip-link" href="#main" [attr.lang]="language()">{{ language() === 'tr' ? 'İçeriğe geç' : 'Skip to content' }}</a>
    <header [attr.lang]="language()">
      <a [routerLink]="language() === 'tr' ? '/preview/tr/home' : '/'" [attr.aria-label]="language() === 'tr' ? 'OrganicSEOOps ana sayfa' : 'OrganicSEOOps home'">OrganicSEOOps</a>
      <span>{{ language() === 'tr' ? 'Geliştirme ön izlemesi' : 'Development preview' }}</span>
    </header>
    <main id="main" tabindex="-1"><router-outlet /></main>
    <footer [attr.lang]="language()">{{ language() === 'tr' ? 'Yerel geliştirme sürümü · Abonelikler ve SEO analizi henüz kullanılamıyor.' : 'Local development build · Subscriptions and SEO analysis are not available yet.' }}
      <app-analytics-preferences [language]="language()" />
    </footer>
  `,
  styles: `
    :host { display: flex; flex-direction: column; min-height: 100dvh; }
    header, main, footer { width: min(100% - 2rem, 68rem); margin-inline: auto; }
    header { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem; padding-block: 1.5rem; border-bottom: 1px solid #c8d5db; }
    header a { font-weight: 750; font-size: 1.2rem; }
    header span { margin-left: auto; font-size: 0.875rem; }
    main { flex: 1; padding-block: clamp(2rem, 8vw, 5rem); }
    footer { padding-block: 1.5rem; border-top: 1px solid #c8d5db; font-size: 0.875rem; }
    .skip-link { position: absolute; top: -5rem; left: 1rem; padding: 0.75rem; background: white; }
    .skip-link:focus { top: 1rem; }
  `,
})
export class App {
  readonly language = signal<'en' | 'tr'>('en');
  private readonly router = inject(Router);

  constructor() {
    const document = inject(DOCUMENT);
    const head = document.head;
    const runtime = document.querySelector<HTMLTemplateElement>('head #public-page-runtime')?.content;
    const update = () => {
      head.querySelectorAll('[rel=canonical],[hreflang],[property^="og:"],[name^="twitter:"],#public-page-schema,[name=robots]')
        .forEach(node => node.remove());
      let route = this.router.routerState.snapshot.root.firstChild;
      const publicRoute = route?.routeConfig?.path === '';
      while (route?.firstChild) route = route.firstChild;
      const path = (route ? this.router.url : document.location?.pathname ?? '')
        .split(/[?#]/, 1)[0].replace(/^\/|\/$/g, '');
      const page = (publicRoute && route?.routeConfig?.path !== '**' || !route)
        ? [...(runtime?.children ?? [])].find(tag => tag.tagName === 'TEMPLATE'
          && tag.getAttribute('data-path')?.replace(/\/$/, '') === path) as HTMLTemplateElement | undefined : undefined;
      if (page) {
        head.querySelectorAll('title,meta[name=description]').forEach(node => node.remove());
        head.append(page.content.cloneNode(true));
        document.documentElement.lang = page.lang;
      } else head.insertAdjacentHTML('beforeend', '<meta name=robots content="noindex, nofollow">');
      this.language.set(page?.lang === 'tr' || route?.data['language'] === 'tr'
        && publicRoute ? 'tr' : 'en');
    };
    update();
    const navigation = this.router.events.subscribe(event => { if (event instanceof NavigationEnd) update(); });
    inject(DestroyRef).onDestroy(() => navigation.unsubscribe());
  }
}
