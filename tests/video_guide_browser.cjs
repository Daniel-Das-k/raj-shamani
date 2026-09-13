// Opt-in live check: queries existing videos, never starts an import.
// NODE_PATH=/private/tmp/knowledge-ui-check/node_modules node tests/video_guide_browser.cjs
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
    let requests = 0;
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (request.url().endsWith('/api/ask')) requests++; });
    await page.goto(process.env.APP_URL || 'http://127.0.0.1:8765');
    await page.waitForFunction(() => document.querySelector('#collection-status').textContent.includes('videos indexed'));
    const status = await page.evaluate(async () => (await fetch('/api/status')).json());
    assert.equal(status.read_only, true);
    assert.equal(status.worker_running, false);
    assert.ok(status.counts.ready > 0);
    assert.equal(await page.locator('#channel-tools').isVisible(), false);
    const consolidated = process.argv.includes('--consolidated-reply');
    const question = consolidated ? 'can u tell me how ill become a billionaire at 22' : 'RACI mein responsible aur accountable ka difference kya hai? Team mein ownership clear karne ke liye ise kaise use karein?';
    await page.locator('#video-scope').selectOption(consolidated ? '' : 'XwawXRaNfzM');
    await page.locator('#question').fill(question);
    const pending = page.waitForResponse(r => r.url().endsWith('/api/ask'), {timeout: 180000});
    await page.locator('#ask-button').click();
    const answer = await (await pending).json();
    const output = `data/ui-checks/video-guide/${new Date().toISOString().replaceAll(':', '-')}`;
    await fs.mkdir(output, {recursive: true});
    await fs.writeFile(`${output}/response.json`, JSON.stringify(answer, null, 2));
    assert.ok(['answered', 'recommendations'].includes(answer.status), JSON.stringify(answer));
    if (consolidated) assert.equal(answer.reply_status, 'ready', JSON.stringify(answer));
    assert.ok(answer.recommendations.length > 0 && answer.recommendations.length <= 3);
    if (consolidated) assert.equal(answer.points.length, 1);
    await page.locator('.answer-references').waitFor();
    assert.equal(await page.locator('.answer-reply').count(), answer.points.length ? 1 : 0);
    if (answer.points.length) {
      assert.ok((await page.locator('.answer-reply').innerText()).includes(answer.points[0].text));
      assert.ok(await page.evaluate(() => Boolean(document.querySelector('.answer-reply').compareDocumentPosition(
        document.querySelector('.answer-references')) & Node.DOCUMENT_POSITION_FOLLOWING)));
      for (const link of await page.locator('.answer-reply .reference-link').all()) {
        assert.equal(await page.locator(await link.getAttribute('href')).count(), 1);
      }
    }
    assert.equal(await page.locator('.evidence').count(), answer.recommendations.length);
    assert.deepEqual(await page.locator('.evidence blockquote').allTextContents(), answer.recommendations.map(r => r.citation.quote));
    for (const [index, card] of answer.recommendations.entries()) {
      const node = page.locator('.evidence').nth(index);
      assert.ok((await node.innerText()).includes(card.summary));
      assert.ok((await node.innerText()).includes(card.why_relevant.replace(/^P\d+\b/, 'This moment').replace(/\bP\d+\b/g, 'another retrieved moment')));
      if (card.match === 'related') assert.ok(card.limitation && (await node.innerText()).includes(card.limitation));
      if (!consolidated) assert.equal(card.citation.source_id, 'XwawXRaNfzM');
      assert.equal(await node.locator('.time-link').getAttribute('href'), card.citation.url);
    }
    assert.equal(await page.locator('.original-transcript[open]').count(), 0);
    const original = page.locator('.original-transcript').first();
    await original.locator('summary').click();
    assert.equal(await original.locator('blockquote').isVisible(), true);
    await original.locator('summary').click();
    await page.locator('.evidence-actions button').first().click();
    const frame = new URL(await page.locator('#player-container iframe').getAttribute('src'));
    assert.equal(Number(frame.searchParams.get('start')), Math.floor(answer.recommendations[0].citation.start));
    assert.equal(Number(frame.searchParams.get('end')), Math.ceil(answer.recommendations[0].citation.end));
    await page.keyboard.press('Escape');
    await page.screenshot({path: `${output}/desktop.png`, fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({path: `${output}/mobile.png`, fullPage: true});
    const saved = await (await page.request.get(new URL(`/api/responses/${answer.record_id}`, page.url()).href)).json();
    assert.deepEqual(saved.response, answer);
    assert.equal(saved.question, question);
    await page.reload();
    await page.locator('#response-history summary').click();
    await page.locator('.saved-response').filter({hasText: question}).first().locator('button').click();
    await page.locator('.answer-references').waitFor();
    assert.equal(requests, 1);
    if (consolidated) assert.ok((await page.locator('.answer-reply').innerText()).includes(answer.points[0].text));
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({output, record_id: answer.record_id, coverage: answer.coverage,
      recommendations: answer.recommendations.length, ready_videos: status.counts.ready,
      desktop: 'passed', mobile: 'passed', history_reopened: true, page_errors: errors}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
