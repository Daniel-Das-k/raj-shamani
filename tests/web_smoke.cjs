// Exercise the shipped browser script with a small DOM/API fixture, without downloads.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

class Node {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.listeners = {};
    this.firstChild = {textContent: ''};
    this.value = '';
    this.textContent = '';
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.listeners.close?.(); }
}

const citation = {
  title: 'Synthetic video', url: 'https://www.youtube.com/watch?v=abcdefghijk&t=100s',
  start: 100.25, end: 104.75, time_range: '00:01:40–00:01:44',
  quote: 'Validation means testing demand.', review_reasons: [],
  summary: 'Test demand to validate an idea.',
};
const answer = {
  status: 'answered', message: 'From the retrieved video excerpts:',
  points: [{text: 'The video describes validation as testing demand.', citations: [citation]}],
};

async function app(responses = [], suppliedStatus = null, history = {items: [], total: 0}) {
  const nodes = new Map();
  const $ = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, new Node());
    return nodes.get(selector);
  };
  const requests = [];
  const context = vm.createContext({
    document: {querySelector: $, querySelectorAll: () => [],
      createElement: (tag) => new Node(tag), createDocumentFragment: () => new Node('fragment')},
    URL, setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => {},
    fetch: async (url, options) => {
      if (url.startsWith('/api/responses?')) return {ok: true, json: async () => history};
      if (url === '/api/status') return {ok: true, json: async () => suppliedStatus || ({
        sources: [{id: 'abcdefghijk', title: citation.title, url: citation.url, status: 'ready', chunks: 1}],
        job: {running: false, items: []}, credentials: {answers: true, transcription: true}, links_count: 1,
      })};
      requests.push({url, data: options?.body ? JSON.parse(options.body) : undefined});
      return {ok: true, json: async () => responses.shift()};
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../knowledge/web/app.js'), 'utf8'), context);
  await new Promise(setImmediate);
  return {context, $, requests};
}

test('direct answers render text, original quote, timestamp link and bounded playback', async () => {
  const {context, $} = await app();
  context.showAnswer(answer);
  const reply = $('#answer').children[0];
  assert.equal(reply.children[0].textContent, answer.points[0].text);
  const references = $('#answer').children[1];
  assert.equal(references.children[0].textContent, 'References');
  const evidence = references.children[1];
  assert.equal(evidence.children[0].children[1].href, citation.url);
  assert.equal(evidence.children[1].textContent, 'Summary');
  assert.equal(evidence.children[2].textContent, citation.summary);
  const original = evidence.children[3];
  assert.equal(original.tag, 'details');
  assert.ok(!original.open);
  assert.equal(original.children[0].textContent, 'Show original excerpt');
  assert.equal(original.children[1].textContent, citation.quote);
  original.open = true;
  original.listeners.toggle();
  assert.equal(original.children[0].textContent, 'Hide original excerpt');
  original.open = false;
  original.listeners.toggle();
  assert.equal(original.children[0].textContent, 'Show original excerpt');
  context.playExcerpt(citation);
  assert.equal($('#player-dialog').open, true);
  assert.equal($('#player-container').children[0].src,
    'https://www.youtube-nocookie.com/embed/abcdefghijk?start=100&end=105&autoplay=1');
  assert.equal($('#external-player').href, citation.url);
  $('#close-player').listeners.click();
  assert.equal($('#player-container').children.length, 0);
  context.showAnswer({status: 'insufficient_evidence', message: 'No supporting excerpts found.', points: []});
  assert.equal($('#answer').children.length, 1);
});

test('clarification carries the original question into the answer request', async () => {
  const { $, requests } = await app([
    {status: 'needs_clarification', message: 'Which topic?', points: []}, answer,
  ]);
  const submit = () => $('#question-form').listeners.submit({preventDefault() {}});
  $('#question').value = 'Explain what they said.';
  await submit();
  assert.equal($('#question').placeholder, 'Which topic?');
  $('#question').value = 'Customer validation.';
  await submit();
  assert.equal(requests[1].data.question, 'Explain what they said.\nAdditional detail: Customer validation.');
  assert.equal($('#question').value, requests[1].data.question);
  assert.equal($('#ask-button').disabled, false);
  $('#reset').listeners.click();
  assert.equal($('#answer').children.length, 0);
  assert.equal($('#question').value, '');
});

test('video guide shows relevance and limits without manufacturing an answer paragraph', async () => {
  const {context, $} = await app();
  const guide = {match: 'related', summary: 'This moment discusses customer feedback.',
    why_relevant: 'It may help you explore demand.', limitation: 'It does not predict your sales.', citation};
  context.showAnswer({status: 'recommendations', coverage: 'related', message: 'Related background, not a direct answer.',
    points: [], recommendations: [guide]});
  assert.equal($('#answer').children[0].textContent, 'Related background, not a direct answer.');
  const section = $('#answer').children[1];
  assert.equal(section.children[0].textContent, 'Suggested video moments');
  const card = section.children[1];
  assert.equal(card.children[0].children[1].href, citation.url);
  assert.ok(card.children.some(n => n.textContent === 'Related discussion · partial match'));
  for (const text of [guide.summary, guide.why_relevant, guide.limitation]) {
    assert.ok(card.children.some(n => n.textContent === text));
  }
  const original = card.children.find(n => n.tag === 'details');
  assert.ok(!original.open);
  assert.equal(original.children[1].textContent, citation.quote);
  assert.ok(!$('#answer').children.some(n => n.className === 'answer-reply'));
  context.showAnswer({status: 'insufficient_evidence', message: 'No useful match.', points: [], recommendations: []});
  assert.equal($('#answer').children.length, 1);
});

test('internal passage IDs are not exposed in a recommendation explanation', async () => {
  const {context, $} = await app();
  context.showAnswer({status: 'recommendations', message: 'Useful moments.', points: [], recommendations: [{
    match: 'direct', summary: 'A complete summary.', why_relevant: 'P2 complements P1 with an example.', limitation: '', citation,
  }]});
  const card = $('#answer').children[1].children[1];
  assert.ok(card.children.some(n => n.textContent === 'This moment complements another retrieved moment with an example.'));
});

test('saved video recommendations reopen with their explanation and no new generation', async () => {
  const recommendation = {match: 'direct', summary: 'This moment covers demand testing.',
    why_relevant: 'It discusses your topic.', limitation: '', citation};
  const response = {status: 'recommendations', message: 'Useful moments.', points: [], recommendations: [recommendation]};
  const record = {question: 'Find demand-testing discussions.', model: 'test', elapsed_seconds: 2,
    created_at: '2026-09-13T00:00:00Z', response};
  const {$, requests} = await app([record], null, {
    items: [{id: 'a'.repeat(32), question: record.question, status: 'recommendations', created_at: record.created_at}], total: 1});
  await new Promise(setImmediate);
  const row = $('#history-list').children[0].children[0];
  assert.match(row.children[1].textContent, /Suggested moments/);
  await row.children[2].children[0].listeners.click();
  assert.equal(requests.length, 1);
  assert.match(requests[0].url, /^\/api\/responses\//);
  assert.equal($('#answer').children[1].children[0].textContent, 'Suggested video moments');
});

test('channel discovery requires an explicit import and uses channel identity', async () => {
  const status = {backend: 'supermemory', channels: [], sources: [], counts: {ready: 3},
    total: 3, credentials: {indexing: true, answers: true}, worker_running: true};
  const preview = {id: 'UCabcdefghijklmnopqrstuv', title: 'Example channel',
    url: 'https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv', sample: []};
  const {$, requests} = await app([preview, {accepted: true}], status);
  assert.equal($('#ask-button').disabled, false);
  assert.equal($('#process').hidden, true);
  $('#channel-handle').value = '@example';
  await $('#channel-form').listeners.submit({preventDefault() {}});
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/channels/preview');
  assert.equal(requests[0].data.channel, '@example');
  assert.equal($('#channel-preview').hidden, false);
  const importButton = $('#channel-preview').children.at(-1);
  await importButton.listeners.click();
  assert.equal(requests[1].url, '/api/channels');
  assert.equal(requests[1].data.channel_id, preview.id);
  assert.equal($('#channel-preview').hidden, true);
});

test('selected video is included in a question request', async () => {
  const {$, requests} = await app([answer]);
  $('#video-scope').value = 'abcdefghijk';
  $('#question').value = 'What is validation?';
  await $('#question-form').listeners.submit({preventDefault() {}});
  assert.equal(requests[0].data.source_id, 'abcdefghijk');
});

test('Raj Shamani reader shows indexed videos without import or pending controls', async () => {
  const video = {id: 'abcdefghijk', title: 'Raj Shamani conversation', url: citation.url, state: 'ready'};
  const status = {backend: 'supermemory', read_only: true, library_title: 'Raj Shamani',
    channels: [], sources: [video], counts: {ready: 1}, total: 1,
    credentials: {indexing: true, answers: true}, worker_running: false};
  const {$, requests} = await app([answer], status);
  for (const id of ['channel-tools', 'add-source', 'process', 'video-filters', 'ingest-note']) {
    assert.equal($('#' + id).hidden, true, id);
  }
  assert.equal($('#collection-status').textContent, '1 video indexed');
  assert.equal($('#source-count').textContent, 'Raj Shamani');
  assert.equal($('#source-list').children[0].children.length, 1);
  assert.equal($('#ask-button').disabled, false);
  assert.equal(requests.length, 0);
  $('#question').value = 'Explain leadership';
  await $('#question-form').listeners.submit({preventDefault() {}});
  assert.equal(requests[0].url, '/api/ask');
});

test('indexed filter paginates only indexed videos and keeps total counts visible', async () => {
  const video = {id: 'abcdefghijk', title: 'Indexed video', url: citation.url, state: 'ready'};
  const status = {backend: 'supermemory', channels: [], sources: [video],
    counts: {ready: 51, queued: 100, skipped: 2}, total: 153,
    credentials: {indexing: true, answers: true}, worker_running: true};
  const {$, requests} = await app([{sources: Array(50).fill(video)}, {sources: [video]}, {sources: []}], status);
  assert.equal($('#video-summary').textContent, '51 indexed · 100 pending · 2 need attention');
  $('#video-filter').value = 'ready';
  await $('#video-filter').listeners.change();
  assert.equal(requests[0].url, '/api/videos?offset=0&status=ready');
  assert.equal($('#video-page-label').textContent, '1–50 of 51');
  assert.equal($('#source-list').children[0].children.length, 50);
  await $('#next-videos').listeners.click();
  assert.equal(requests[1].url, '/api/videos?offset=50&status=ready');
  assert.equal($('#video-page-label').textContent, '51–51 of 51');
  assert.equal($('#next-videos').disabled, true);
  $('#video-filter').value = 'attention';
  await $('#video-filter').listeners.change();
  assert.equal(requests[2].url, '/api/videos?offset=0&status=attention');
  assert.equal($('#previous-videos').disabled, true);
});

test('saved responses reopen without another answer call and provide a JSON download', async () => {
  const id = 'a'.repeat(32);
  const record = {id, created_at: '2026-09-12T12:00:00Z', question: 'A saved question',
    model: 'test-model', elapsed_seconds: 2.5, response: answer};
  const {$, requests} = await app([record], null, {total: 1, items: [{...record, status: 'answered'}]});
  assert.equal($('#history-count').textContent, '(1)');
  const row = $('#history-list').children[0].children[0];
  const actions = row.children[2];
  assert.equal(actions.children[1].href, `/api/responses/${id}`);
  assert.equal(actions.children[1].download, `response-${id}.json`);
  await actions.children[0].listeners.click();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, `/api/responses/${id}`);
  assert.equal($('#question').value, record.question);
  assert.equal($('#answer').children[0].children[0].textContent, answer.points[0].text);
  assert.match($('#request-status').textContent, /Saved response/);
});

test('one reply precedes deduplicated references while quotes remain unchanged', async () => {
  const {context, $} = await app();
  const original = {...citation, quote: 'Um, I I think >> [laughs] this could work.'};
  const input = {status: 'answered', message: 'From the video', points: [
    {text: 'The speaker suggests that this could work.', citations: [original]},
    {text: 'This is a possibility rather than a guaranteed outcome.', citations: [{...original}]},
  ]};
  context.showAnswer(input);
  const reply = $('#answer').children[0], references = $('#answer').children[1];
  assert.equal(reply.className, 'answer-reply');
  assert.equal(reply.children.length, 2);
  assert.equal(reply.children[0].textContent, input.points[0].text);
  assert.equal(reply.children[1].textContent, input.points[1].text);
  assert.equal(reply.children[0].children[0].href, '#answer-reference-1');
  assert.equal(reply.children[1].children[0].href, '#answer-reference-1');
  assert.equal(references.children.length, 2); // Heading + one shared reference.
  assert.equal(references.children[1].id, 'answer-reference-1');
  assert.equal(references.children[1].children[3].children[1].textContent, original.quote);
});

test('older saved references remain readable without a generated summary', async () => {
  const {context} = await app();
  const old = {...citation};
  delete old.summary;
  const evidence = context.evidenceNode(old, 1);
  assert.equal(evidence.children[1].tag, 'details');
  assert.equal(evidence.children[1].children[1].textContent, old.quote);
});
