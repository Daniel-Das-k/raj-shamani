// Reproduce a stale clarification in the browser, then send one real new question.
// NODE_PATH=/private/tmp/knowledge-ui-check/node_modules node tests/clarification_browser.cjs
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
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    const output = `data/ui-checks/clarification/${new Date().toISOString().replaceAll(':', '-')}`;
    await fs.mkdir(output, {recursive: true});
    await page.route('**/api/ask', async route => {
      requests.push(route.request().postDataJSON());
      if (requests.length === 1) {
        await route.fulfill({json: {status: 'needs_clarification',
          message: 'What specific strategies or fields are you interested in for becoming a billionaire?', points: []}});
      } else await route.continue();
    });
    await page.goto(process.env.APP_URL || 'http://127.0.0.1:8765');
    await page.waitForFunction(() => document.querySelector('#collection-status').textContent.includes('videos indexed'));
    await page.locator('#question').fill('can u tell me how ill become a billionaire at 22');
    await page.locator('#ask-button').click();
    await page.locator('.answer-note').filter({hasText: 'What specific strategies'}).waitFor();
    assert.equal(await page.locator('#followup-option').count(), 0);
    assert.match(await page.locator('#ask-button').innerText(), /Ask library/);
    await page.setViewportSize({width: 390, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({path: `${output}/clarification-mobile.png`, fullPage: true});
    await page.setViewportSize({width: 1440, height: 1000});
    const question = 'how to tell to my boss my opinon on a matter of si ject';
    await page.locator('#question').fill(question);
    const pending = page.waitForResponse(r => r.url().endsWith('/api/ask'), {timeout: 180000});
    await page.locator('#ask-button').click();
    const answer = await (await pending).json();
    await fs.writeFile(`${output}/result.json`, JSON.stringify({first_response_simulated: true, requests, question, answer}, null, 2));
    assert.deepEqual(requests[1], {question});
    assert.ok(['answered', 'recommendations', 'insufficient_evidence'].includes(answer.status), JSON.stringify(answer));
    assert.equal(await page.locator('#followup-option').count(), 0);
    if (answer.points?.length) await page.locator('.answer-reply').waitFor();
    await page.screenshot({path: `${output}/boss-reply-desktop.png`, fullPage: true});
    const saved = await (await page.request.get(new URL(`/api/responses/${answer.record_id}`, page.url()).href)).json();
    assert.equal(saved.question, question);
    assert.deepEqual(saved.response, answer);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({output, record_id: answer.record_id, status: answer.status,
      reply_status: answer.reply_status, stale_context_removed: true, page_errors: errors}));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
