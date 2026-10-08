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
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const authRequests = [];
    page.on('request', request => { if (request.url().includes('/auth/')) authRequests.push(request.url()); });
    let owner = 'alice', csrf = 'alice-csrf', failSave = false, failRead = false, heldRead = null;
    const stored = {alice: {revision: 0, items: [{id: 'watch-later', name: 'Watch later', items: []}]},
                    bob: {revision: 0, items: [{id: 'watch-later', name: 'Watch later', items: []}]}};
    await context.route(origin + '/', route => route.fulfill({contentType: 'text/html', body: html}));
    await context.route('**/api/account', route => route.fulfill({json: {id: owner, email: owner + '@example.test', csrf}}));
    await context.route('**/api/collections', async route => {
      const request = route.request(), headers = request.headers();
      assert.equal(headers['x-account-id'], owner);
      if (request.method() === 'PUT') {
        assert.equal(headers['x-csrf-token'], csrf);
        if (failSave) return route.fulfill({status: 503, json: {error: 'Could not save right now.'}});
        const update = request.postDataJSON();
        if (update.revision !== stored[owner].revision) return route.fulfill({status: 409, json: {error: 'Collections changed in another tab.'}});
        stored[owner] = {items: update.items, revision: update.revision + 1};
      }
      const snapshot = structuredClone(stored[owner]);
      if (request.method() === 'GET') {
        if (failRead) return route.fulfill({status: 503, json: {error: 'Could not refresh right now.'}});
        if (heldRead) { const hold = heldRead; heldRead = null; hold.started(); await hold.released; }
      }
      return route.fulfill({json: snapshot});
    });
    await context.route('**/api/responses?*', route => route.fulfill({json: {items: [], total: 0}}));
    await page.addInitScript(() => localStorage.setItem('figuring-out.collections.v1', JSON.stringify([
      {id: 'legacy', name: 'Private local collection', items: []},
    ])));
    await page.goto(origin);
    await page.locator('.editorial-lead').waitFor();
    assert.equal(await page.locator('#account-button').isVisible(), !guest);
    await page.locator('.editorial-list [data-save-key]').first().click();
    await page.locator('#collection-name').fill('Alice collection');
    await page.locator('#confirm-save').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Saved to Alice collection'));
    assert.equal(stored.alice.revision, 1);
    assert.equal(await page.locator('#collection-count').textContent(), '2', 'Watch later and Alice collection both count');
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
    await page.waitForFunction(() => document.querySelector('#ask-button').getAttribute('aria-label') !== 'Search the archive');
    assert.equal(await page.locator('#account-button').isVisible(), !guest);
    assert.doesNotMatch(await page.locator('#collection-tabs').textContent(), /Alice collection|Added on another device/);
    assert.equal(await page.locator('#collection-count').textContent(), '1');
    assert.equal(await page.locator('#collection-count').getAttribute('aria-label'), '1 collection');
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({width, height: 900});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Account button must fit the header');
    }
    await page.locator('.main-nav [data-view=discover]').click();
    await page.locator('.editorial-list [data-save-key]').first().click();
    await page.locator('#confirm-save').click();
    await page.locator('#save-dialog').waitFor({state: 'hidden'});
    assert.equal(await page.locator('#collection-count').textContent(), '1');
    assert.equal(await page.locator('.editorial-list [data-save-key]').first().getAttribute('aria-pressed'), 'true');
    const peer = await context.newPage();
    peer.on('pageerror', error => errors.push(error.message));
    await peer.goto(origin);
    await peer.locator('.editorial-lead').waitFor();
    await peer.locator('.main-nav [data-view=saved]').click();
    await peer.locator('#saved-grid .catalog-card').waitFor();

    await page.locator('.main-nav [data-view=saved]').click();
    await page.getByRole('button', {name: 'Remove from collection', exact: true}).click();
    await page.locator('#saved-grid .catalog-card').waitFor({state: 'detached'});
    await peer.locator('#saved-grid .catalog-card').waitFor({state: 'detached'});
    assert.equal(await page.locator('#collection-count').textContent(), '1', 'Removing a video does not remove its collection');
    assert.equal(await peer.locator('#collection-count').textContent(), '1');
    assert.equal(await peer.locator('#saved-grid .catalog-card').count(), 0, 'A removal updates another open tab without reloading');
    assert.equal(await page.locator('.editorial-list [data-save-key]').first().getAttribute('aria-pressed'), 'false');

    await page.locator('#new-collection').click();
    await page.locator('#collection-name').fill('Current collection');
    await page.locator('#confirm-save').click();
    await page.locator('#save-dialog').waitFor({state: 'hidden'});
    const selected = await page.locator('#collection-tabs [aria-pressed=true]').textContent();
    assert.match(selected, /Current collection/);
    assert.equal(await page.locator('#collection-count').textContent(), '2', 'An empty new collection immediately increments the count');
    assert.equal(await page.locator('#collection-count').getAttribute('aria-label'), '2 collections');
    await peer.waitForFunction(() => document.querySelector('#collection-count').textContent === '2');
    await page.reload();
    await page.locator('#collection-tabs button').filter({hasText: 'Current collection'}).click();
    assert.equal(await page.locator('#collection-count').textContent(), '2', 'Empty collections still count after reload');
    await page.locator('.main-nav [data-view=discover]').click();
    await page.locator('.editorial-list [data-save-key]').first().click();
    assert.equal(await page.locator('#collection-select option:checked').textContent(), 'Current collection');
    await page.locator('#confirm-save').click();
    await page.locator('#save-dialog').waitFor({state: 'hidden'});
    assert.equal(await page.locator('#collection-count').textContent(), '2', 'Saving an item does not increment the number of collections');
    await peer.locator('#collection-tabs button').filter({hasText: 'Current collection'}).click();
    await peer.locator('#saved-grid .catalog-card').waitFor();
    assert.equal(await peer.locator('#saved-grid .catalog-card').count(), 1, 'New saves update other open tabs');

    let releaseRead, readStarted;
    const started = new Promise(resolve => { readStarted = resolve; });
    heldRead = {started: readStarted, released: new Promise(resolve => { releaseRead = resolve; })};
    await page.evaluate(() => { window.pendingCollectionRefresh = refreshCollections(); });
    await started;
    await page.locator('.editorial-lead [data-save-key]').click();
    await page.locator('#confirm-save').click();
    await page.locator('#save-dialog').waitFor({state: 'hidden'});
    releaseRead();
    await page.evaluate(() => window.pendingCollectionRefresh);
    assert.equal(await page.locator('#collection-count').textContent(), '2');
    await page.locator('.main-nav [data-view=saved]').click();
    assert.equal(await page.locator('#saved-grid .catalog-card').count(), 2, 'A delayed old GET cannot undo a completed save');
    await peer.waitForFunction(() => document.querySelectorAll('#saved-grid .catalog-card').length === 2);
    assert.equal(await peer.locator('#saved-grid .catalog-card').count(), 2);

    stored.bob = {revision: stored.bob.revision + 1, items: [...stored.bob.items,
      {id: 'external', name: 'Saved elsewhere', items: []}]};
    await page.locator('.main-nav [data-view=saved]').click();
    await page.locator('#collection-tabs button').filter({hasText: 'Saved elsewhere'}).waitFor();
    assert.equal(await page.locator('#collection-count').textContent(), '3', 'A collection added elsewhere updates the count');
    stored.bob = {revision: stored.bob.revision + 1, items: stored.bob.items.filter(item => item.id !== 'external')};
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(() => !document.querySelector('#collection-tabs').textContent.includes('Saved elsewhere'));
    assert.equal(await page.locator('#collection-count').textContent(), '2');

    failRead = true;
    await page.locator('.main-nav [data-view=discover]').click();
    await page.locator('.main-nav [data-view=saved]').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Collections could not refresh'));
    assert.equal(await page.locator('#saved-grid .catalog-card').count(), 2, 'A failed refresh preserves saved items');
    assert.equal(await page.locator('#collection-count').textContent(), '2', 'A failed refresh preserves the last confirmed count');
    failRead = false;
    await peer.close();
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
    console.log(`${guest ? 'Guest' : 'Account'} browser checks passed: collection counts including empty collections, immediate saved state, cross-tab saves/removals, selected collection, stale reads, navigation/focus refresh, failed saves/refreshes, conflicts, isolation, reload and mobile layout.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
