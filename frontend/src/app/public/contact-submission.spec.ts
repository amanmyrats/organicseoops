import { PLATFORM_ID } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { ContactSubmission } from './contact-submission';

const bootstrap = () => ({ csrfToken: 'a'.repeat(64), scope_hint: 'b'.repeat(64), expires_at: Math.floor(Date.now() / 1000) + 172800 });
const response = (body: unknown, ok = true) => ({ ok, json: async () => body }) as Response;
const receipt = (key: string) => ({ request_key: key, status: 'received', created_at: new Date(Date.now() - 1000).toISOString(),
  expires_at: new Date(Date.now() + 172800000).toISOString(), scope: 'stored_contact_not_email_delivery_or_staff_response' });

describe('Configured anonymous CONTACT submission', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  function setup(language: 'en' | 'tr' = 'en') {
    const fixture = TestBed.createComponent(ContactSubmission);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    return fixture;
  }
  function fill(root: HTMLElement) {
    const form = root.querySelector<HTMLFormElement>('form')!;
    form.querySelector<HTMLInputElement>('[name="reply_email"]')!.value = 'fixture@example.invalid';
    form.querySelector<HTMLTextAreaElement>('[name="question"]')!.value = 'Synthetic safe question';
    form.querySelector<HTMLInputElement>('[name="no_sensitive_data"]')!.checked = true;
    return form;
  }

  it('requires explicit browser bootstrap, fails closed when disabled and renders labeled EN/TR controls only when configured', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({}, false)).mockResolvedValueOnce(response(bootstrap()));
    vi.stubGlobal('fetch', fetch);
    const fixture = setup('tr'), instance = fixture.componentInstance, root: HTMLElement = fixture.nativeElement;
    expect(fetch).not.toHaveBeenCalled(); expect(root.querySelector('form')).toBeNull();
    root.querySelector<HTMLButtonElement>('button')!.click(); await fixture.whenStable(); fixture.detectChanges();
    expect(instance.state()).toBe('idle'); expect(root.textContent).toContain('yapılandırılmamış');
    await instance.open(); fixture.detectChanges();
    for (const id of ['contact-category', 'contact-email', 'contact-question']) {
      expect(root.querySelector(`label[for="${id}"]`)).toBeTruthy(); expect(root.querySelector(`#${id}`)).toBeTruthy();
    }
    expect(root.querySelector('section')?.lang).toBe('tr');
    expect(root.querySelector('[role="status"]')?.textContent).toContain('özgün tarayıcı');
    const form = fill(root); form.querySelector<HTMLInputElement>('[name="no_sensitive_data"]')!.checked = false;
    await instance.submit(form); expect(fetch).toHaveBeenCalledTimes(2);
    fixture.componentRef.setInput('language', 'en'); fixture.detectChanges();
    expect(root.querySelector('form')).toBeNull(); expect(instance.state()).toBe('idle');
    expect(root.textContent).toContain('Local intake has not been opened');
    TestBed.resetTestingModule(); TestBed.configureTestingModule({ providers: [{ provide: PLATFORM_ID, useValue: 'server' }] });
    await setup().componentInstance.open(); expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('holds one immutable uncertain command and original scope, allowing only explicit unchanged retry after null readback without browser storage', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem'), readStorage = vi.spyOn(Storage.prototype, 'getItem');
    const fetch = vi.fn().mockResolvedValueOnce(response(bootstrap())).mockRejectedValueOnce(new Error('lost'))
      .mockResolvedValueOnce(response({ receipt: null })).mockImplementationOnce(async (_url, init: RequestInit) =>
        response(receipt(JSON.parse(init.body as string).request_key)));
    vi.stubGlobal('fetch', fetch);
    const fixture = setup(), instance = fixture.componentInstance, root: HTMLElement = fixture.nativeElement;
    await instance.open(); fixture.detectChanges(); const form = fill(root);
    await instance.submit(form); fixture.detectChanges();
    expect(instance.state()).toBe('uncertain'); expect(root.querySelector('fieldset')?.disabled).toBe(true);
    const sent = JSON.parse(fetch.mock.calls[1][1].body);
    form.querySelector<HTMLTextAreaElement>('textarea')!.value = 'Changed after uncertainty';
    await instance.retry(); expect(fetch).toHaveBeenCalledTimes(2);
    await instance.inspect(); expect(instance.absent()).toBe(true);
    await instance.retry(); fixture.detectChanges();
    expect(instance.state()).toBe('stored'); expect(root.querySelector('form')).toBeNull();
    expect(JSON.parse(fetch.mock.calls[3][1].body)).toEqual(sent);
    expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({ request_key: sent.request_key });
    for (const [, init] of fetch.mock.calls.slice(1)) {
      expect(init.headers['X-Contact-Scope']).toBe('b'.repeat(64));
      expect(init.credentials).toBe('same-origin'); expect(init.cache).toBe('no-store');
      expect(init.redirect).toBe('error'); expect(init.referrerPolicy).toBe('no-referrer');
    }
    expect(fetch.mock.calls.filter(([url]) => url.endsWith('/csrf/'))).toHaveLength(1);
    expect(root.textContent).toContain('delivery and staff response are not confirmed');
    expect(storage).not.toHaveBeenCalled(); expect(readStorage).not.toHaveBeenCalled();
  });

  it('reconciles a postcommit lost response through own receipt without another create', async () => {
    let stored: unknown;
    const fetch = vi.fn().mockResolvedValueOnce(response(bootstrap())).mockImplementationOnce(async (_url, init: RequestInit) => {
      stored = receipt(JSON.parse(init.body as string).request_key); throw new Error('lost response');
    }).mockImplementationOnce(async () => response({ receipt: stored }));
    vi.stubGlobal('fetch', fetch);
    const fixture = setup(), instance = fixture.componentInstance;
    await instance.open(); fixture.detectChanges(); await instance.submit(fill(fixture.nativeElement));
    await instance.inspect(); await instance.retry();
    expect(instance.state()).toBe('stored'); expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith('/create/'))).toHaveLength(1);
  });

  it('treats malformed receipts and changed-cookie denial as unconfirmed and never enables retry', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response(bootstrap())).mockResolvedValueOnce(response(receipt('wrong-key')))
      .mockResolvedValueOnce(response({ receipt: null, extra: true })).mockResolvedValueOnce(response({}, false))
      .mockResolvedValueOnce(response({ receipt: { ...receipt('wrong-key'), scope: 'email_delivered' } }));
    vi.stubGlobal('fetch', fetch);
    const fixture = setup(), instance = fixture.componentInstance;
    await instance.open(); fixture.detectChanges(); await instance.submit(fill(fixture.nativeElement));
    expect(instance.state()).toBe('uncertain');
    for (let index = 0; index < 3; index++) {
      await instance.inspect(); expect(instance.absent()).toBe(false); await instance.retry();
    }
    expect(fetch).toHaveBeenCalledTimes(5); expect(instance.status()).toContain('unconfirmed');
  });

  it('does not renew expired pending authority and clears page memory with late responses fenced on exit', async () => {
    const context = bootstrap();
    const fetch = vi.fn().mockResolvedValueOnce(response(context)).mockRejectedValueOnce(new Error('uncertain'));
    vi.stubGlobal('fetch', fetch);
    const fixture = setup(), instance = fixture.componentInstance;
    await instance.open(); fixture.detectChanges(); await instance.submit(fill(fixture.nativeElement));
    vi.spyOn(Date, 'now').mockReturnValue(context.expires_at * 1000);
    await instance.inspect(); await instance.retry(); await instance.open();
    expect(instance.state()).toBe('expired'); expect(fetch).toHaveBeenCalledTimes(2);
    expect(instance.status()).toContain('No automatic renewal');
    vi.restoreAllMocks();
    window.dispatchEvent(new Event('pagehide')); fixture.detectChanges();
    expect(instance.state()).toBe('idle'); expect(fixture.nativeElement.querySelector('form')).toBeNull();
    let release!: (value: Response) => void;
    fetch.mockResolvedValueOnce(response(bootstrap())).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    await instance.open(); fixture.detectChanges(); const pending = instance.submit(fill(fixture.nativeElement));
    const key = JSON.parse(fetch.mock.calls[3][1].body).request_key;
    fixture.destroy(); release(response(receipt(key))); await pending;
    expect(instance.state()).toBe('idle'); expect(instance.status()).toBe('Local intake has not been opened.');
  });
});
