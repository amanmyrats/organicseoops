import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { vi } from 'vitest';
import { AccountApi } from './account-api';
import { Acquisition } from './acquisition';

function body(count: number | null = 2) {
  return { dictionary_version: 'acquisition-v1', basis: 'current_unexpired_public_consent_epochs', funnel_rates_available: false,
    milestones: {
      public_page_view: { state: count === null ? 'unavailable' : 'derivable', count, grain: 'consent_epoch_route_locale' },
      public_cta_selected: { state: count === null ? 'unavailable' : 'derivable', count, grain: 'consent_epoch_route_locale_cta' },
    }, cleanup: { expired_pending: false, deadline_missed: false } };
}

describe('Separate deliberate staff public observation projection', () => {
  it.each(['en', 'tr'] as const)('keeps public grains separate, handles expiry/withdrawal decrease and policy-off unavailable in %s', async (language) => {
    const api = { productLanguage: vi.fn(async () => ({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } })), acquisitionMilestones: vi.fn(async () => ({ status: 403, body: {} })),
      publicAnalyticsObservations: vi.fn(async () => ({ status: 200, body: body() })) };
    TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api }] });
    const fixture = TestBed.createComponent(Acquisition); fixture.detectChanges();
    const component = fixture.componentInstance; await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector("section").getAttribute("lang")).toBe(language);
    expect(api.publicAnalyticsObservations).not.toHaveBeenCalled();
    Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>).find(button => button.textContent === (language === 'tr' ? 'Saklanan genel sayfa sayılarını incele' : 'Inspect retained public counts'))!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(component.publicRows()[0]).toMatchObject({ count: 2, grain: 'consent_epoch_route_locale' });
    expect(component.milestones()).toEqual([]);
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'operasyonel ölçüm birimleriyle hiçbir zaman birleştirilmez' : 'never join the operational grains');
    const rows = component.publicRows(); component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.publicRows()).toBe(rows); expect(api.publicAnalyticsObservations).toHaveBeenCalledTimes(1);
    component.productLanguage.set(language); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('span[lang="en"]').textContent).toBe('consent_epoch_route_locale');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Tarayıcı tarafından bildirilen sayfanın ilk sunucu alındı kayıtları' : 'Browser-reported page first server receipts');
    api.publicAnalyticsObservations.mockResolvedValue({ status: 200, body: body(0) });
    await component.loadPublic(); expect(component.publicRows()[0].count).toBe(0);
    api.publicAnalyticsObservations.mockResolvedValue({ status: 200, body: body(null) });
    await component.loadPublic(); fixture.detectChanges();
    expect(component.publicRows()[0].count).toBeNull();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Kullanılamıyor — yayın politikası kapalı' : 'Unavailable — publication policy is off');
    for (const cleanup of [{ expired_pending: true, deadline_missed: false }, { expired_pending: true, deadline_missed: true }]) {
      api.publicAnalyticsObservations.mockResolvedValue({ status: 200, body: { ...body(), cleanup } }); await component.loadPublic(); fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain(cleanup.deadline_missed ? language === 'tr' ? 'Son tarih aşıldı' : 'Deadline missed' : language === 'tr' ? 'kayıtlar kaldırılmayı bekliyor' : 'records pending removal');
    }
    const invalid = body(); invalid.milestones.public_page_view.grain = 'organization';
    api.publicAnalyticsObservations.mockResolvedValue({ status: 200, body: invalid }); await component.loadPublic(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Genel sayfa gözlem sayıları kullanılamıyor veya hatalı biçimde.' : 'Public observation counts unavailable or malformed.');
  });

  it('rejects malformed or mixed grains and drops late destroyed responses without identifiers', async () => {
    const api = { acquisitionMilestones: vi.fn(async () => ({ status: 403, body: {} })),
      publicAnalyticsObservations: vi.fn(async () => ({ status: 200, body: body() })) };
    TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api }] });
    const fixture = TestBed.createComponent(Acquisition), component = fixture.componentInstance;
    const invalid = body(); invalid.milestones.public_page_view.grain = 'organization';
    api.publicAnalyticsObservations.mockResolvedValue({ status: 200, body: invalid });
    await component.loadPublic(); expect(component.publicRows()).toEqual([]); expect(component.publicError()).toContain('malformed');
    let resolve!: (value: { status: number; body: ReturnType<typeof body> }) => void;
    api.publicAnalyticsObservations.mockImplementation(() => new Promise(done => resolve = done));
    const pending = component.loadPublic(); fixture.destroy(); resolve({ status: 200, body: body() }); await pending;
    expect(component.publicRows()).toEqual([]); expect(component.publicCleanup()).toBeNull();
  });
});
