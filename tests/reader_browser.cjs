// The new reader: real browsing plus isolated provider fixtures. No paid requests.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const origin = process.env.APP_URL || 'http://127.0.0.1:8000';
  const output = path.join(__dirname, '../data/reader-check');
  await fs.mkdir(output, {recursive: true});
  const browser = await chromium.launch(process.env.CHROME_PATH
    ? {headless: true, executablePath: process.env.CHROME_PATH}
    : {headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}, deviceScaleFactor: 1});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const overflow = async () => {
      const bad = await page.evaluate(() => ({width: innerWidth, actual: document.documentElement.scrollWidth, nodes: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1 && el.getBoundingClientRect().width > 0).slice(0, 8).map(el => `${el.tagName}.${el.className}`)}));
      if (bad.actual > bad.width) { console.log(bad); await page.screenshot({path: path.join(output, 'overflow.png'), fullPage: true}); }
      assert.ok(bad.actual <= bad.width, 'Horizontal overflow');
    };
    await page.emulateMedia({reducedMotion: 'reduce', colorScheme: 'light'});
    await page.goto(origin);
    await page.locator('.editorial-lead').waitFor();
    await page.waitForFunction(() => document.querySelector('#search-mode').textContent !== 'Loading archive…');
    await page.evaluate(() => document.fonts.ready);
    await overflow();
    assert.equal(await page.locator('.traffic-lights, .app-window').count(), 0);
    assert.equal(await page.locator('.feature-media img').evaluate(image => image.complete && image.naturalWidth > 0), true);
    await page.screenshot({path: path.join(output, 'discovery-desktop.png'), fullPage: true});

    await page.emulateMedia({colorScheme: 'dark'});
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    assert.equal(await page.locator('#theme-toggle').getAttribute('aria-pressed'), 'true');
    await page.screenshot({path: path.join(output, 'dark-discovery-desktop.png'), fullPage: true});
    await page.locator('#theme-toggle').click();
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light', 'Manual light choice survives reload under dark OS');
    await page.locator('#theme-toggle').click();
    await page.emulateMedia({colorScheme: 'light'});
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark', 'Manual dark choice overrides light OS and survives reload');
    await page.locator('.editorial-lead').waitFor();
    await page.locator('[data-save]').first().click();
    await page.screenshot({path: path.join(output, 'dark-save-dialog.png')});
    await page.keyboard.press('Escape');
    for (const width of [320, 390, 768]) {
      await page.setViewportSize({width, height: 844});
      await overflow();
      if (width === 390) await page.screenshot({path: path.join(output, 'dark-discovery-mobile.png'), fullPage: true});
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.locator('#theme-toggle').click();

    await page.getByRole('button', {name: 'Watch the Andrew Huberman conversation', exact: true}).click();
    assert.match(await page.locator('#video-container iframe').getAttribute('src'), /Y566_T-YlNQ/);
    await page.getByRole('button', {name: 'Close video', exact: true}).click();
    // The native dialog queues its close event, which removes the player.
    await page.locator('#video-container iframe').waitFor({state: 'detached'});
    assert.equal(await page.locator('#video-container iframe').count(), 0);

    await page.locator('#home-topics button').filter({hasText: 'Mind & body'}).click();
    assert.equal(await page.locator('#catalog-topics button[aria-pressed=true]').textContent(), 'Mind & body');
    assert.ok(await page.locator('#catalog-grid .catalog-card').count() > 0);
    await page.getByRole('button', {name: 'Clear filters', exact: true}).click();
    assert.equal(await page.locator('#catalog-grid .catalog-card').count(), 12);
    await page.locator('#load-more').click();
    assert.equal(await page.locator('#catalog-grid .catalog-card').count(), 24);
    await page.locator('#catalog-search').fill('Huberman');
    assert.equal(await page.locator('#catalog-grid .catalog-card').count(), 1);
    await page.screenshot({path: path.join(output, 'catalog-desktop.png'), fullPage: true});

    await page.locator('#catalog-grid .icon-button').click();
    await page.locator('#collection-name').fill('Ideas to revisit');
    await page.locator('#confirm-save').click();
    assert.match(await page.locator('#toast').textContent(), /Saved to Ideas to revisit/);
    await page.locator('.main-nav [data-view=saved]').click();
    assert.equal(await page.locator('#saved-grid .catalog-card').count(), 1);
    await page.reload();
    await page.locator('#collection-tabs button').filter({hasText: 'Ideas to revisit'}).click();
    assert.equal(await page.locator('#saved-grid .catalog-card').count(), 1, 'Saved item survives reload');
    await page.screenshot({path: path.join(output, 'collection-desktop.png'), fullPage: true});
    await page.getByRole('button', {name: 'Remove from collection', exact: true}).click();
    assert.equal(await page.locator('#saved-grid .catalog-card').count(), 0);
    await page.locator('#new-collection').click();
    await page.locator('#collection-name').fill('Building my business');
    await page.locator('#confirm-save').click();
    assert.ok(await page.locator('#collection-tabs').textContent().then(text => text.includes('Building my business')));

    await page.locator('.main-nav [data-view=discover]').click();
    await page.waitForFunction(() => document.querySelector('#toast').hidden);
    for (const width of [390, 320, 768]) {
      await page.setViewportSize({width, height: 844});
      await overflow();
      if (width === 390) await page.screenshot({path: path.join(output, 'discovery-mobile.png'), fullPage: true});
    }
    await page.locator('#about-button').click();
    assert.equal(await page.locator('#about-dialog').evaluate(el => el.open), true);
    await page.getByRole('button', {name: 'Close archive information', exact: true}).click();

    // Only the following section mocks answer/index availability. Browsing above is real.
    const video = {id: 'Y566_T-YlNQ', title: 'Andrew Huberman: Daily Habits', state: 'ready'};
    const citation = {source_id: video.id, title: video.title, start: 100, end: 130, time_range: '01:40–02:10',
      url: `https://www.youtube.com/watch?v=${video.id}&t=100s`, quote: 'Synthetic fixture: consistent routines can help you focus.'};
    const answer = {status: 'answered', record_id: 'a'.repeat(32), points: [{text: 'A consistent routine can make it easier to focus.', citations: [citation]}],
      recommendations: [{match: 'related', summary: 'The excerpt connects everyday routines to focus.', why_relevant: 'It discusses the role of routine.', limitation: 'It does not establish a personal outcome.', citation}]};
    let requests = 0, failure = false, releaseRequest;
    let heldRequest = null;
    const sent = [], records = new Map();
    records.set('a'.repeat(32), {question: 'How can I focus better?', source_id: video.id, response: answer, created_at: '2026-09-15T08:00:00Z'});
    await page.route('**/api/status', route => route.fulfill({json: {backend: 'supermemory', read_only: true, credentials: {answers: true, indexing: true}, sources: [video], counts: {ready: 1}, total: 1}}));
    await page.route('**/api/ask/stream', async route => {
      requests++;
      const payload = route.request().postDataJSON(); sent.push(payload);
      const id = requests.toString(16).padStart(32, '0');
      const response = failure ? {error: 'Test fixture: the provider is temporarily unavailable.', record_id: id} : {...answer, record_id: id};
      records.set(id, {question: payload.question, source_id: payload.source_id, response, created_at: '2026-09-15T08:00:00Z'});
      if (heldRequest) await heldRequest;
      return route.fulfill({contentType: 'application/x-ndjson', body: [
        {type: 'stage', message: 'Searching original conversations…'},
        {type: 'excerpts', excerpts: [citation], message: 'Checking the answer…'},
        {type: 'answer', response, http_status: failure ? 500 : 200},
      ].map(x => JSON.stringify(x)).join('\n') + '\n'});
    });
    await page.route('**/api/responses?*', route => route.fulfill({json: {total: 1, items: [{id: 'a'.repeat(32), question: 'How can I focus better?', created_at: '2026-09-15T08:00:00Z', status: 'answered'}]}}));
    await page.route(/\/api\/responses\/[a-f0-9]{32}$/, route => route.fulfill({json: records.get(route.request().url().split('/').pop())}));
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(origin);
    await page.waitForFunction(() => document.querySelector('#search-mode').textContent === 'Ask the archive');
    await page.locator('#video-scope').selectOption(video.id);
    await page.locator('#question').fill('How can I focus better?');
    await page.locator('#question').press('Enter');
    await page.locator('.answer-prose').waitFor();
    assert.equal(sent[0].source_id, video.id);
    assert.equal(await page.locator('.moment').count(), 1);
    assert.equal(await page.locator('#watch-panel').isVisible(), true);
    await page.waitForFunction(() => { const image = document.querySelector('#watch-container img'); return image?.complete && image.naturalWidth > 0; });
    assert.equal(await page.locator('.citation-link').getAttribute('href'), '#moment-1');
    const savedAnswerURL = page.url();
    await page.locator('.citation-link').click();
    assert.equal(page.url(), savedAnswerURL, 'Citation jump preserves the saved answer URL for refresh');
    assert.equal(await page.locator('#moment-1').evaluate(el => document.activeElement === el), true);
    await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    await overflow();
    await page.screenshot({path: path.join(output, 'answer-desktop.png'), fullPage: true});
    await page.locator('#theme-toggle').click();
    await page.screenshot({path: path.join(output, 'dark-answer-desktop.png'), fullPage: true});
    await page.locator('#theme-toggle').click();
    await page.getByText('Read the original excerpt', {exact: true}).click();
    assert.equal(await page.locator('.moment blockquote').textContent(), citation.quote);
    await page.route('https://www.youtube-nocookie.com/**', route => route.fulfill({contentType: 'text/html', body: '<html><body>Offline player fixture</body></html>'}));
    await page.getByRole('button', {name: 'Play from 1:40', exact: true}).click();
    assert.match(await page.locator('#watch-container iframe').getAttribute('src'), /start=100&end=130/);
    await page.getByRole('button', {name: 'Save this moment', exact: true}).click();
    await page.locator('#collection-name').fill('Focus');
    await page.locator('#confirm-save').click();
    await page.setViewportSize({width: 390, height: 844});
    await overflow();
    await page.screenshot({path: path.join(output, 'answer-mobile.png'), fullPage: true});
    await page.getByRole('button', {name: 'Close supporting video', exact: true}).click();
    assert.equal(await page.locator('#watch-container iframe').count(), 0);
    await page.locator('.main-nav [data-view=saved]').click();
    await page.locator('.history-row button').click();
    await page.locator('.answer-prose').waitFor();
    assert.equal(requests, 1, 'History reopening must not generate another answer');
    await page.locator('#ask-again').click();
    assert.equal(await page.locator('#question').evaluate(el => document.activeElement === el), true);
    assert.equal(await page.locator('#answer-view').isVisible(), true, 'Ask another stays with the answer');
    await page.locator('#question').fill('How do I build a business?');
    await page.locator('#video-scope').selectOption('');
    await page.locator('.main-nav [data-view=saved]').click();
    await page.locator('#return-to-answer').click();
    assert.equal(await page.locator('#question').inputValue(), 'How do I build a business?', 'Draft survives browsing');
    assert.equal(await page.locator('.answer-prose').isVisible(), true);
    assert.equal(requests, 1, 'Returning to the current question must not regenerate it');
    await page.locator('#question').press('Enter');
    await page.waitForFunction(() => document.querySelector('#asked-question').textContent === 'How do I build a business?' && !document.querySelector('#ask-button').disabled);
    assert.deepEqual(sent[1], {question: 'How do I build a business?'}, 'Next question is independent and uses the visible scope');
    assert.equal(await page.locator('#question').inputValue(), '', 'Successful submission leaves an empty composer');
    await page.goBack();
    await page.waitForFunction(() => document.querySelector('#asked-question').textContent === 'How can I focus better?');
    assert.equal(requests, 2, 'Back restores the previous saved answer without generation');
    await page.goForward();
    await page.waitForFunction(() => document.querySelector('#asked-question').textContent === 'How do I build a business?');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#asked-question').textContent === 'How do I build a business?');
    assert.equal(requests, 2, 'Refresh restores the saved answer');
    failure = true;
    await page.locator('#question').fill('What helps with sleep?');
    await page.locator('#question').press('Enter');
    await page.locator('#retry-question').waitFor();
    await page.waitForFunction(() => !document.querySelector('#ask-button').disabled);
    failure = false;
    heldRequest = new Promise(resolve => { releaseRequest = resolve; });
    await page.locator('#question').fill('A draft for later');
    await page.locator('#retry-question').click();
    await page.waitForFunction(() => document.querySelector('#ask-button').disabled);
    assert.equal(await page.locator('#question').inputValue(), 'A draft for later', 'Retry preserves the next question draft');
    await page.locator('#ask-again').click();
    await page.locator('#question').fill('Can I prepare my next question?');
    await page.locator('#question').press('Enter');
    assert.equal(requests, 4, 'Typing while busy must not submit another request');
    releaseRequest(); heldRequest = null;
    await page.waitForFunction(() => !document.querySelector('#ask-button').disabled);
    assert.equal(await page.locator('#question').inputValue(), 'Can I prepare my next question?', 'Completion preserves a draft typed while waiting');
    assert.deepEqual(sent[3], sent[2], 'Retry uses the failed question and its original scope');
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({width, height: 900});
      await overflow();
      await page.locator('#ask-again').click();
      assert.equal(await page.locator('#question').evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 100 && r.bottom <= innerHeight; }), true, 'Composer focus stays visible below the header');
      await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
      await page.screenshot({path: path.join(output, `question-flow-${width}.png`), fullPage: true});
    }
    assert.deepEqual(errors, []);
    console.log('Reader checks passed: catalog, playback, collections, light/dark themes, responsive layouts, citations, repeat questions in place, drafts, visible scope, retry, busy submission guard, Back/Forward, refresh, and saved-answer reopening without generation.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
