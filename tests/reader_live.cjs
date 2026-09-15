// Opt-in check against the running app and paid providers. No mocked APIs.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const origin = process.env.APP_URL || 'http://127.0.0.1:8000';
  const question = 'What does Andrew Huberman say about sleep and getting sunlight in the morning?';
  const output = path.join(__dirname, '../data/reader-live-check');
  await fs.mkdir(output, {recursive: true});
  const browser = await chromium.launch(process.env.CHROME_PATH
    ? {headless: true, executablePath: process.env.CHROME_PATH}
    : {headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    // Observe a clone of the real stream; Chrome's network inspector can discard
    // streamed response bodies while the page is still rendering them.
    await page.addInitScript(() => {
      const fetchOriginal = window.fetch;
      window.fetch = async (...args) => {
        const response = await fetchOriginal(...args);
        if (new URL(response.url).pathname === '/api/ask/stream') {
          window.liveCheckStream = response.clone().text();
        }
        return response;
      };
    });
    const errors = [];
    let requests = 0;
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (new URL(request.url()).pathname === '/api/ask/stream') requests++;
    });
    await page.goto(origin);
    await page.waitForFunction(() => document.querySelector('#search-mode')?.textContent === 'Ask the archive');
    const statusResponse = await page.request.get(origin + '/api/status');
    assert.ok(statusResponse.ok());
    const status = await statusResponse.json();
    const video = status.sources.find(source => source.title.includes('Andrew Huberman'));
    assert.ok(video, 'The live archive must contain the Huberman episode');
    await page.locator('#video-scope').selectOption(video.id);
    await page.locator('#question').fill(question);
    const responsePromise = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/ask/stream', {timeout: 300000});
    await page.locator('#question').press('Enter');
    const response = await responsePromise;
    assert.equal(response.status(), 200);
    await page.waitForFunction(() => !document.querySelector('#ask-button').disabled, null, {timeout: 300000});
    const events = (await page.evaluate(() => window.liveCheckStream)).trim().split('\n').map(line => JSON.parse(line));
    const final = events.find(event => event.type === 'answer');
    assert.ok(final, 'The stream must deliver a final answer');
    await fs.writeFile(path.join(output, 'response.json'), JSON.stringify({question, source_id: video.id, events}, null, 2));
    assert.equal(final.http_status, 200, final.response.error);
    const answer = final.response;
    assert.ok(answer.points?.length, answer.message || 'Expected a substantive answer');
    assert.ok(answer.record_id, 'The backend must persist the response');
    const prose = await page.locator('.answer-prose > p').evaluateAll(nodes => nodes.map(node =>
      [...node.childNodes].filter(child => child.nodeType === Node.TEXT_NODE).map(child => child.textContent).join('')));
    assert.deepEqual(prose, answer.points.map(point => point.text), 'Display the exact backend prose');
    assert.ok(await page.locator('.moment').count() > 0, 'Source moments must render');
    assert.ok(await page.locator('.citation-link').count() > 0, 'The answer must link to evidence');
    const recordResponse = await page.request.get(origin + '/api/responses/' + answer.record_id);
    assert.ok(recordResponse.ok());
    assert.deepEqual((await recordResponse.json()).response, answer);
    await page.screenshot({path: path.join(output, 'answer.png'), fullPage: true});
    await page.locator('.main-nav [data-view=saved]').click();
    await page.locator('.history-row button').filter({hasText: question}).first().click();
    await page.locator('.answer-prose').waitFor();
    assert.equal(requests, 1, 'Reopening history must reuse the saved answer');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({result: 'passed', indexed_videos: status.total, question,
      answer: answer.points.map(point => point.text), record_id: answer.record_id,
      stream_events: events.map(event => event.type), requests, output}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
