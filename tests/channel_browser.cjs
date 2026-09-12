// Optional integration check against a running channel server. No channel import.
// npm install --prefix /private/tmp/knowledge-ui-check playwright
// NODE_PATH=/private/tmp/knowledge-ui-check/node_modules node tests/channel_browser.cjs
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.APP_URL || 'http://127.0.0.1:8765');
    await page.waitForFunction(() => document.querySelector('#collection-status').textContent.includes('videos indexed'));
    const status = await page.evaluate(async () => (await fetch('/api/status')).json());
    assert.equal(status.backend, 'supermemory');
    assert.ok(status.counts.ready > 0);
    if (status.read_only) {
      assert.equal(status.library_title, 'Raj Shamani');
      assert.equal(status.total, status.counts.ready);
      assert.equal(status.worker_running, false);
      for (const selector of ['#channel-tools', '#add-source', '#process', '#video-filters', '#ingest-note']) {
        assert.equal(await page.locator(selector).isVisible(), false, selector);
      }
      const code = await page.evaluate(async () => (await fetch('/api/channels/action', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({channel_id: 'UCzwCEE_PchiBULMnAJqhGVg', action: 'resume'}),
      })).status);
      assert.equal(code, 403);
    } else {
      const filtered = page.waitForResponse(r => r.url().includes('/api/videos?offset=0&status=ready'));
      await page.locator('#video-filter').selectOption('ready');
      await filtered;
    }
    await page.waitForFunction(() => document.querySelector('#source-list').querySelectorAll('.source-item').length > 0);
    assert.equal(await page.locator('#source-list .source-item').count(), Math.min(50, status.counts.ready));
    assert.equal(await page.locator('#source-list .source-state:not(.ready)').count(), 0);
    if (!status.read_only) {
    await page.locator('#channel-handle').fill('@rajshamani');
    await page.locator('#find-channel').click();
    await page.locator('#channel-preview').waitFor({state: 'visible', timeout: 90000});
    assert.match(await page.locator('#channel-preview').innerText(), /Raj Shamani/);
    assert.match(await page.locator('#channel-preview').innerText(), /Shorts are excluded/);
    assert.equal(await page.locator('#channel-preview button').innerText(), 'Import long-form videos');
    assert.equal((await page.evaluate(async () => (await fetch('/api/status')).json())).channels.length, status.channels.length);
    }
    await fs.mkdir('data/ui-checks', {recursive: true});
    await page.screenshot({path: 'data/ui-checks/channel-desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({path: 'data/ui-checks/channel-mobile.png', fullPage: true});
    const shopping = process.argv.includes('--shopping-reply');
    const direct = process.argv.includes('--direct-reply');
    const allSources = shopping || direct;
    if (process.argv.includes('--live-answer') || process.argv.includes('--record-response') || allSources) {
      const question = direct ? 'can u tell me the how to become billionaire' : shopping ? 'can u tell me how the shopping in future will be like' : 'What does the CTO say about taking responsibility for outcomes?';
      await page.setViewportSize({width: 1440, height: 1000});
      await page.locator('#video-scope').selectOption(allSources ? '' : 'XwawXRaNfzM');
      await page.locator('#question').fill(question);
      const response = page.waitForResponse(r => r.url().endsWith('/api/ask'), {timeout: 120000});
      await page.locator('#ask-button').click();
      const result = await (await response).json();
      await fs.writeFile('data/ui-checks/live-answer.json', JSON.stringify(result, null, 2));
      if (process.argv.includes('--live-answer') || allSources) {
        assert.equal(result.status, 'answered', JSON.stringify(result));
        assert.ok(result.points.length);
      }
      for (const point of result.points || []) {
        assert.ok(point.citations.length);
        for (const cite of point.citations) {
          if (!allSources) assert.equal(cite.source_id, 'XwawXRaNfzM');
          assert.ok(cite.end > cite.start);
          assert.ok(cite.url.includes(`&t=${Math.floor(cite.start)}s`));
        }
      }
      await page.locator('#ask-button').waitFor({state: 'visible'});
      if (process.argv.includes('--record-response') || allSources) {
        assert.match(result.record_id, /^[a-f0-9]{32}$/);
        const saved = await (await page.request.get(new URL(`/api/responses/${result.record_id}`, page.url()).href)).json();
        assert.deepEqual(saved.response, result);
        assert.equal(saved.question, question);
        assert.equal(saved.source_id, allSources ? null : 'XwawXRaNfzM');
        await page.reload();
        await page.locator('#response-history summary').click();
        const row = page.locator('.saved-response').filter({hasText: saved.question}).first();
        await row.locator('button').click();
        await page.waitForFunction(question => document.querySelector('#question').value === question, saved.question);
        assert.equal(await row.locator('a').getAttribute('download'), `response-${result.record_id}.json`);
        const after = await page.evaluate(async () => (await fetch('/api/status')).json());
        assert.deepEqual(after.channels.map(c => [c.id, c.paused]), status.channels.map(c => [c.id, c.paused]));
        console.log(JSON.stringify({record_id: result.record_id, saved_status: saved.status, history_reopened: true}));
      }
      if (allSources) {
        await page.locator('.answer-references').waitFor();
        assert.equal(await page.locator('.answer-reply .reply-paragraph').count(), result.points.length);
        const expectedQuotes = [...new Set(result.points.flatMap(p => p.citations.map(c => c.quote)))];
        assert.deepEqual(await page.locator('.answer-references blockquote').allTextContents(), expectedQuotes);
        assert.equal(await page.locator('.answer-reply blockquote').count(), 0);
        assert.ok(await page.evaluate(() => Boolean(document.querySelector('.answer-reply').compareDocumentPosition(document.querySelector('.answer-references')) & Node.DOCUMENT_POSITION_FOLLOWING)));
        const artifact = direct ? 'direct-reply' : 'shopping-reply';
        if (direct) {
          const paragraphs = result.points.map(p => p.text).join('\n');
          assert.doesNotMatch(paragraphs, /the (episode|video|speaker) (says|discusses|explains)|>>|\[laughter\]/i);
          for (const cite of result.points.flatMap(p => p.citations)) {
            assert.ok(cite.summary && cite.summary.length <= 500);
            assert.doesNotMatch(cite.summary, />>|\[laughter\]/i);
          }
          assert.equal(await page.locator('.reference-summary').count(), expectedQuotes.length);
          assert.equal(await page.locator('.original-transcript[open]').count(), 0);
          const original = page.locator('.original-transcript').first();
          assert.equal(await original.locator('blockquote').isVisible(), false);
          await original.locator('summary').click();
          assert.equal(await original.locator('blockquote').isVisible(), true);
          await original.locator('summary').click();
        }
        await page.screenshot({path: `data/ui-checks/${artifact}-desktop.png`, fullPage: true});
        await page.setViewportSize({width: 390, height: 844});
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
        await page.screenshot({path: `data/ui-checks/${artifact}-mobile.png`, fullPage: true});
        await fs.writeFile(`data/ui-checks/${artifact}-answer.json`, JSON.stringify(result, null, 2));
      }
      await page.screenshot({path: 'data/ui-checks/channel-answer.png', fullPage: true});
      console.log(JSON.stringify({answer_status: result.status || 'error', points: result.points?.length || 0}));
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ready_videos: status.counts.ready, read_only: Boolean(status.read_only), desktop: 'passed', mobile: 'passed', page_errors: errors}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
