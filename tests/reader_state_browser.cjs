const assert = require('node:assert/strict');

module.exports = async function checkReaderState(page) {
  const rows = Array.from({length: 21}, (_, i) => ({id: i.toString(16).padStart(32, '0'),
    question: 'History question ' + i, status: 'answered', created_at: '2026-10-01T00:00:00Z'}));
  let releaseFirst, first = true, failOlder = true;
  const held = new Promise(resolve => { releaseFirst = resolve; });
  const offsets = [];
  await page.route('**/api/responses?*', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    offsets.push(offset);
    if (first) {
      first = false;
      await held;
      return route.fulfill({json: {items: [{...rows[0], question: 'Stale history'}], total: 1}});
    }
    if (offset && failOlder) return route.fulfill({status: 503, json: {error: 'Temporarily unavailable'}});
    return route.fulfill({json: {items: rows.slice(offset, offset + 20), total: 21}});
  });
  await page.locator('.main-nav [data-view=saved]').click();
  await page.locator('#history-tab').click();
  await page.waitForFunction(() => document.querySelector('#history-more').disabled);
  await page.locator('.main-nav [data-view=discover]').click();
  await page.locator('.main-nav [data-view=saved]').click();
  await page.waitForFunction(() => document.querySelectorAll('.history-row').length === 20);
  const staleResponse = page.waitForResponse(response => response.url().includes('/api/responses?') && response.status() === 200);
  releaseFirst();
  // Wait for the older response to be consumed before checking the visible list.
  await (await staleResponse).finished();
  assert.equal(await page.locator('.history-row').count(), 20);
  assert.equal(await page.getByText('Stale history', {exact: true}).count(), 0);
  await page.locator('#history-more').click();
  await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Older questions could not load'));
  assert.equal(await page.locator('.history-row').count(), 20, 'Page failure must preserve already loaded questions');
  failOlder = false;
  await page.locator('#history-more').click();
  await page.waitForFunction(() => document.querySelectorAll('.history-row').length === 21);
  assert.deepEqual(offsets, [0, 0, 20, 20], 'Retry must request the failed page again instead of skipping it');
  assert.equal(await page.locator('#history-more').isVisible(), false);

  const videos = Array.from({length: 52}, (_, i) => ({id: 'video' + String(i).padStart(6, '0'), title: 'Video ' + i, state: 'ready'}));
  await page.route('**/api/status', route => route.fulfill({json: {backend: 'supermemory', read_only: true,
    credentials: {answers: true, indexing: true}, counts: {ready: 52}, total: 52, sources: videos.slice(0, 50)}}));
  await page.route('**/api/videos?*', route => {
    const url = new URL(route.request().url());
    assert.equal(url.searchParams.get('status'), 'ready');
    assert.equal(url.searchParams.get('offset'), '50');
    return route.fulfill({json: {sources: videos.slice(50)}});
  });
  await page.evaluate(() => refreshStatus());
  assert.equal(await page.evaluate(() => readyVideos().length), 52);
  assert.equal(await page.evaluate(id => findVideo(id).title, videos[51].id), videos[51].title);
  assert.equal(await page.locator('#video-scope').count(), 0);

  await page.locator('.main-nav [data-view=saved]').click();
  await page.locator('#collections-tab').click();
  await page.evaluate(() => {
    const key = 'figuring-out.collections.v1';
    localStorage.setItem(key, JSON.stringify([{id: 'keep', name: 'Preserved collection', items: [
      null, {id: 'Y566_T-YlNQ', title: 'Saved conversation', kind: 'episode'},
    ]}]));
    dispatchEvent(new StorageEvent('storage', {key}));
  });
  assert.match(await page.locator('#collection-tabs').textContent(), /Preserved collection/);
  assert.equal(await page.locator('#saved-grid .catalog-card').count(), 1);
  console.log('Reader state checks passed: stale history, pagination retry, all indexed videos, and partial collection recovery.');
};
