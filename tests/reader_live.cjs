// Opt-in check against the running app and paid providers. No mocked APIs.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const origin = process.env.APP_URL || 'http://127.0.0.1:8000';
  const question = 'What does Andrew Huberman say about sleep and getting sunlight in the morning?';
  const output = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, '../data/reader-live-check');
  await fs.mkdir(output, {recursive: true});
  const browser = await chromium.launch(process.env.CHROME_PATH
    ? {headless: true, executablePath: process.env.CHROME_PATH}
    : {headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    // Observe chunks as the app reads them. A cloned response can reject when
    // the app aborts the completed stream immediately after its final answer.
    await page.addInitScript(() => {
      const fetchOriginal = window.fetch;
      window.fetch = async (...args) => {
        const response = await fetchOriginal(...args);
        if (new URL(response.url).pathname === '/api/ask/stream') {
          window.liveCheckEvents = [];
          const getReader = response.body.getReader.bind(response.body);
          response.body.getReader = (...options) => {
            const reader = getReader(...options);
            const read = reader.read.bind(reader);
            const decoder = new TextDecoder();
            let buffer = '';
            reader.read = async () => {
              const part = await read();
              buffer += decoder.decode(part.value || new Uint8Array(), {stream: !part.done});
              let newline;
              while ((newline = buffer.indexOf('\n')) >= 0) {
                const line = buffer.slice(0, newline);
                if (line.trim()) window.liveCheckEvents.push(JSON.parse(line));
                buffer = buffer.slice(newline + 1);
              }
              if (part.done && buffer.trim()) window.liveCheckEvents.push(JSON.parse(buffer));
              return part;
            };
            return reader;
          };
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
    // Keep the generated-answer checks independent of YouTube availability. The
    // separate deployed-player check exercises real playback and automatic stop.
    await page.route('https://www.youtube-nocookie.com/embed/**', route => route.fulfill({
      contentType: 'text/html', body: '<p>Player navigation fixture</p>',
    }));
    await page.emulateMedia({colorScheme: 'light', reducedMotion: 'reduce'});
    await page.goto(origin);
    await page.waitForFunction(() => canAnswer());
    // The reader supplies the current guest/account headers as well as cookies.
    const status = await page.evaluate(() => api('/api/status'));
    assert.equal(status.answer_model, 'gpt-4.1-mini');
    const video = status.sources.find(source => source.title.includes('Andrew Huberman'));
    assert.ok(video, 'The live archive must contain the Huberman episode');
    await page.locator('#question').fill(question);
    const responsePromise = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/ask/stream', {timeout: 300000});
    await page.locator('#question').press('Enter');
    const response = await responsePromise;
    assert.equal(response.status(), 200);
    assert.equal(await page.locator('#question-form').isVisible(), false);
    assert.equal(await page.locator('#ask-again').isVisible(), false);
    assert.equal(await page.locator('#answer-progress').isVisible(), true);
    await page.screenshot({path: path.join(output, 'generating.png'), fullPage: true});
    await page.waitForFunction(() => !document.querySelector('#ask-button').disabled, null, {timeout: 300000});
    const events = await page.evaluate(() => window.liveCheckEvents);
    const final = events.find(event => event.type === 'answer');
    assert.ok(final, 'The stream must deliver a final answer');
    await fs.writeFile(path.join(output, 'response.json'), JSON.stringify({question, events}, null, 2));
    assert.equal(final.http_status, 200, final.response.error);
    assert.deepEqual(events.filter(event => event.type === 'stage').map(event => event.phase), ['search', 'compose']);
    assert.equal(await page.locator('#answer-progress').isVisible(), false);
    assert.equal(await page.locator('#question-form').isVisible(), true);
    const answer = final.response;
    assert.ok(answer.points?.length, answer.message || 'Expected a substantive answer');
    assert.ok(answer.record_id, 'The backend must persist the response');
    const displayedPoints = answer.answer_parts || answer.points;
    const prose = await page.locator('.answer-prose p:not(.answer-limitation)').evaluateAll(nodes => nodes.map(node =>
      [...node.childNodes].filter(child => child.nodeType === Node.TEXT_NODE).map(child => child.textContent).join('')));
    assert.deepEqual(prose, displayedPoints.map(point => point.text), 'Display the exact backend prose');
    assert.ok(await page.locator('.moment').count() > 0, 'Source moments must render');
    assert.ok(await page.locator('.citation-link').count() > 0, 'The answer must link to evidence');
    const record = await page.evaluate(id => api('/api/responses/' + id), answer.record_id);
    assert.deepEqual(record.response, answer);
    const answerURL = page.url();
    const expected = new Map();
    for (const item of [...(answer.recommendations || []), ...answer.points.flatMap(point => point.citations.map(citation => ({citation})))]) {
      const citation = item.citation;
      const key = `${citation.source_id}:${citation.start}:${citation.end}`;
      if (!expected.has(key)) expected.set(key, item);
    }
    const clips = [...expected.values()];
    assert.equal(await page.locator('.moment').count(), clips.length, 'All distinct final references have a visible clip');
    assert.equal(await page.locator('.moment details, .moment blockquote').count(), 0);
    assert.equal(await page.locator('#watch-panel').isVisible(), false);
    for (let i = 0; i < clips.length; i++) {
      const item = clips[i], citation = item.citation;
      const card = page.locator('.moment').nth(i);
      assert.equal(await card.locator('.clip-source').textContent(), citation.title);
      if (item.clip_title) assert.equal(await card.locator('h3').textContent(), item.clip_title);
      const description = item.summary || item.why_relevant || citation.summary;
      if (description) assert.equal(await card.locator('.moment-copy').textContent(), description);
      if (item.limitation) assert.equal(await card.locator('.moment-limit').textContent(), item.limitation);
      assert.equal(await card.locator('.moment-actions > *').count(), 2);
      const fullVideo = card.locator('.moment-actions a');
      assert.equal(await fullVideo.getAttribute('href'), 'https://www.youtube.com/watch?v=' + citation.source_id);
      assert.equal(await fullVideo.getAttribute('target'), '_blank');
      await card.locator('.moment-actions button').click();
      const frame = new URL(await page.locator('#watch-container iframe').getAttribute('src'));
      assert.equal(frame.pathname, '/embed/' + citation.source_id);
      assert.equal(frame.searchParams.get('start'), String(Math.floor(citation.start)));
      assert.equal(frame.searchParams.get('end'), String(Math.ceil(citation.end)));
      assert.equal(page.url(), answerURL, 'Playing any clip preserves the saved answer URL');
    }
    assert.equal(await page.locator('#watch-details a').count(), 0);
    for (let p = 0; p < displayedPoints.length; p++) {
      const paragraph = page.locator('.answer-prose p:not(.answer-limitation)').nth(p);
      const numbers = await paragraph.locator('.citation-link').allTextContents();
      const required = [...new Set(displayedPoints[p].citations.map(citation => clips.findIndex(item =>
        item.citation.source_id === citation.source_id && item.citation.start === citation.start && item.citation.end === citation.end) + 1))];
      assert.deepEqual(numbers.map(Number), required, 'Each answer paragraph points to the correct clips');
    }
    await page.getByRole('button', {name: 'Close supporting video', exact: true}).click();
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({width, height: 1000});
      await page.evaluate(async () => {
        await document.fonts.ready;
        window.scrollTo({top: 0, behavior: 'instant'});
        await new Promise(requestAnimationFrame);
      });
      const layout = await page.evaluate(() => ({
        width: innerWidth, actual: document.documentElement.scrollWidth,
        clipped: [...document.querySelectorAll('.answer-prose p, .moment-copy, .moment-limit, .moment h3')]
          .filter(node => node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1).length,
      }));
      assert.ok(layout.actual <= layout.width, `No horizontal overflow at ${width}px`);
      assert.equal(layout.clipped, 0, `Generated text remains fully readable at ${width}px`);
      await page.screenshot({path: path.join(output, `answer-${width}.png`), fullPage: true});
    }
    await page.locator('#theme-toggle').click();
    await page.screenshot({path: path.join(output, 'answer-dark.png'), fullPage: true});
    await page.locator('#theme-toggle').click();
    await page.locator('.main-nav [data-view=saved]').click();
    await page.locator('#history-tab').click();
    await page.locator('.history-row button').filter({hasText: question}).first().click();
    await page.locator('.answer-prose').waitFor();
    assert.equal(requests, 1, 'Reopening history must reuse the saved answer');
    await page.reload();
    await page.locator('.answer-prose').waitFor();
    assert.equal(requests, 1, 'Refreshing the saved answer must not regenerate it');
    assert.equal(await page.locator('.moment').count(), clips.length);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({result: 'passed', indexed_videos: status.total, question,
      answer: displayedPoints.map(point => point.text), record_id: answer.record_id,
      stream_events: events.map(event => event.type), requests, output}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
