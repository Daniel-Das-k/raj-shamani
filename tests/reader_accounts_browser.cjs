// Production account UI with simulated identity/storage APIs; no credentials or paid calls.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const origin = process.env.APP_URL || 'http://127.0.0.1:8000';
  const guest = process.env.GUEST_MODE === '1';
  const html = (await fs.readFile(path.join(__dirname, '../knowledge/web/index.html'), 'utf8'))
    .replace('data-accounts="local"', `data-accounts="${guest ? 'guest' : 'required'}"`);
  const browser = await chromium.launch(process.env.CHROME_PATH
    ? {headless: true, executablePath: process.env.CHROME_PATH} : {headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const authRequests = [];
    page.on('request', request => { if (request.url().includes('/auth/')) authRequests.push(request.url()); });
    let owner = 'alice', csrf = 'alice-csrf', failSave = false;
    const stored = {alice: {revision: 0, items: [{id: 'watch-later', name: 'Watch later', items: []}]},
                    bob: {revision: 0, items: [{id: 'watch-later', name: 'Watch later', items: []}]}};
    await page.route(origin + '/', route => route.fulfill({contentType: 'text/html', body: html}));
    await page.route('**/api/account', route => route.fulfill({json: {id: owner, email: owner + '@example.test', csrf}}));
    await page.route('**/api/collections', async route => {
      const request = route.request(), headers = request.headers();
      assert.equal(headers['x-account-id'], owner);
      if (request.method() === 'PUT') {
        assert.equal(headers['x-csrf-token'], csrf);
        if (failSave) return route.fulfill({status: 503, json: {error: 'Could not save right now.'}});
        const update = request.postDataJSON();
        if (update.revision !== stored[owner].revision) return route.fulfill({status: 409, json: {error: 'Collections changed in another tab.'}});
        stored[owner] = {items: update.items, revision: update.revision + 1};
      }
      return route.fulfill({json: stored[owner]});
    });
    await page.route('**/api/responses?*', route => route.fulfill({json: {items: [], total: 0}}));
    await page.addInitScript(() => localStorage.setItem('figuring-out.collections.v1', JSON.stringify([
      {id: 'legacy', name: 'Private local collection', items: []},
    ])));
    await page.goto(origin);
    await page.locator('.editorial-lead').waitFor();
    assert.equal(await page.locator('#account-button').isVisible(), !guest);
    await page.locator('[data-save]').first().click();
    await page.locator('#collection-name').fill('Alice collection');
    await page.locator('#confirm-save').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Saved to Alice collection'));
    assert.equal(stored.alice.revision, 1);
    await page.reload();
    await page.locator('.main-nav [data-view=saved]').click();
    await page.locator('#collection-tabs button').filter({hasText: 'Alice collection'}).click();
    assert.equal(await page.locator('#saved-grid .catalog-card').count(), 1);
    assert.equal(await page.getByText('Private local collection', {exact: true}).count(), 0);
    assert.match(await page.locator('#collection-storage-note').textContent(), guest ? /this browser.*30 days/ : /across your devices/);

    failSave = true;
    await page.getByRole('button', {name: 'Remove from collection', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Could not save right now'));
    assert.equal(await page.locator('#saved-grid .catalog-card').count(), 1, 'Failed cloud saves must not claim data was removed');
    failSave = false;
    stored.alice = {revision: 2, items: [{id: 'external', name: 'Added on another device', items: []}]};
    await page.getByRole('button', {name: 'Remove from collection', exact: true}).click();
    await page.locator('#collection-tabs button').filter({hasText: 'Added on another device'}).waitFor();
    assert.equal(stored.alice.revision, 2, 'A stale update must not overwrite another device');

    owner = 'bob'; csrf = 'bob-csrf';
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#search-mode').textContent !== 'Loading archive…');
    assert.equal(await page.locator('#account-button').isVisible(), !guest);
    assert.doesNotMatch(await page.locator('#collection-tabs').textContent(), /Alice collection|Added on another device/);
    assert.equal(await page.locator('#saved-count').textContent(), '0');
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({width, height: 900});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Account button must fit the header');
    }
    await page.route('**/auth/logout', route => {
      assert.equal(route.request().headers()['x-csrf-token'], 'bob-csrf');
      return route.fulfill({json: {redirect: origin + '/signed-out'}});
    });
    await page.route('**/signed-out', route => route.fulfill({contentType: 'text/html', body: '<p>Signed out</p>'}));
    if (guest) {
      assert.deepEqual(authRequests, [], 'Guest UI must never request sign-in or sign-out');
      assert.match(await page.locator('#history-storage-note').textContent(), /this browser/);
    } else {
      await page.locator('#account-button').click();
      await page.waitForURL('**/signed-out');
    }
    assert.deepEqual(errors, []);
    console.log(`${guest ? 'Guest' : 'Account'} browser checks passed: cloud saves, reload, failed saves, conflicts, isolated storage, mobile header and expected authentication UI.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
