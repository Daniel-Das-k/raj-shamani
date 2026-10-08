'use strict';
const $ = selector => document.querySelector(selector);
const svgNS = 'http://www.w3.org/2000/svg';
const topics = ['Mind & body', 'Business & money', 'Work & ambition', 'Life & perspective', 'World & society'];
const storageKey = 'figuring-out.collections.v1';
const guestMode = document.documentElement.dataset.accounts === 'guest';
const accountRequired = guestMode || document.documentElement.dataset.accounts === 'required';
let account = null, collectionRevision = 0, collectionsReady = !accountRequired;
let collectionLoadVersion = 0, collectionSaving = false;
const collectionChannel = accountRequired && typeof BroadcastChannel === 'function'
  ? new BroadcastChannel('figuring-out.collections.changed') : null;
let catalog = [], status = null, view = 'discover', topic = '', query = '', visibleCount = 12;
let collections = [], currentCollection = '', pendingSave = null, busy = false, historyOffset = 0;
let toastTimer, statusTimer, lastFocused = null;
let answerRoute = 'answer', lastQuestion = null, navigationVersion = 0;
let historyVersion = 0, statusVersion = 0;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function icon(name) {
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(svgNS, 'use'); use.setAttribute('href', '#i-' + name); svg.append(use);
  return svg;
}
function button(label, className, callback, iconName) {
  const node = el('button', className, label); node.type = 'button';
  if (iconName) node.append(icon(iconName));
  node.addEventListener('click', callback); return node;
}
function iconButton(label, name, callback) {
  const node = button('', 'icon-button', callback, name); node.setAttribute('aria-label', label); return node;
}
function external(label, url) {
  const a = el('a', 'text-link', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
  a.addEventListener('click', stopVideo); a.append(icon('up')); return a;
}
function videoID(item) { return item?.source_id || item?.id || ''; }
function validID(id) { return typeof id === 'string' && /^[A-Za-z0-9_-]{11}$/.test(id); }
function fullVideoURL(item) {
  const id = videoID(item);
  return validID(id) ? `https://www.youtube.com/watch?v=${id}` : '';
}
function timeLabel(value) { const s = Math.floor(Math.max(0, Number(value) || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function clipKey(item) {
  return validID(videoID(item)) && Number.isFinite(item?.start) && item.start >= 0 && Number.isFinite(item.end) && item.end > item.start
    ? `${videoID(item)}:${item.start}:${item.end}` : '';
}
function clipRange(item) { return `${timeLabel(item.start)}–${timeLabel(Math.ceil(item.end))}`; }
function findVideo(id) { return catalog.find(v => v.id === id) || readyVideos().find(v => v.id === id); }
function readyVideos() { return (status?.sources || []).filter(v => v.state === 'ready' || v.status === 'ready'); }
function canAnswer() { return Boolean(status?.credentials?.answers && readyVideos().length); }
function toast(message) {
  clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
}
function accountHeaders(extra = {}) {
  return {...extra, ...(accountRequired && account ? {'X-Account-ID': account.id, 'X-CSRF-Token': account.csrf} : {})};
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {...options, headers: accountHeaders(options.headers), signal: controller.signal}); const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error || 'The library could not be reached. Please try again.');
      error.status = response.status; throw error;
    }
    return result;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('The library took too long to respond. Please try again.');
    throw error;
  } finally { clearTimeout(timeout); }
}
function imageFor(item, alt = '') {
  const image = el('img'); image.alt = alt; image.loading = 'lazy';
  image.src = item.quote && findVideo(videoID(item))?.portrait || `https://i.ytimg.com/vi/${videoID(item)}/hqdefault.jpg`;
  image.addEventListener('error', () => {
    image.src = '/favicon.svg'; image.classList.add('image-unavailable');
    image.alt = alt ? `${alt} — thumbnail unavailable` : '';
  }, {once: true});
  return image;
}
function itemKey(item) {
  const moment = item.kind === 'moment' || typeof item.quote === 'string';
  return `${videoID(item)}:${moment ? `${Number(item.start) || 0}:${Number(item.end) || 0}` : 'episode'}`;
}
function saveButton(item, label) {
  const node = iconButton(label, 'save', () => openSave(item));
  node.dataset.saveKey = itemKey(item); markSaved(node); return node;
}
function markSaved(node) {
  const key = node.dataset.saveKey || `${node.dataset.save}:episode`;
  const names = collections.filter(c => c.items.some(item => itemKey(item) === key)).map(c => c.name);
  node.setAttribute('aria-pressed', String(Boolean(names.length)));
  node.title = names.length ? `Saved in ${names.join(', ')}` : 'Save to collection';
  node.disabled = collectionSaving || !collectionsReady;
}
function updateSaveButtons() {
  document.querySelectorAll('[data-save], [data-save-key]').forEach(markSaved);
  document.querySelectorAll('.remove-save, #new-collection').forEach(node => { node.disabled = collectionSaving || !collectionsReady; });
}
function savedItem(item) {
  const id = videoID(item);
  if (!validID(id)) throw new Error('This conversation cannot be saved.');
  const kind = item.kind === 'moment' || typeof item.quote === 'string' ? 'moment' : 'episode';
  const value = {id, title: String(item.title || item.display_title || 'Conversation').slice(0, 700), kind};
  if (kind === 'moment') {
    value.start = Math.max(0, Number(item.start) || 0); value.end = Math.max(value.start, Number(item.end) || value.start);
    value.quote = String(item.quote || '').slice(0, 30000);
  }
  return value;
}
function loadCollections() {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw === null) return [{id: 'watch-later', name: 'Watch later', items: []}];
    const rows = JSON.parse(raw);
    if (!Array.isArray(rows) || rows.length > 100) throw new Error('Invalid collections');
    return rows.filter(c => c && typeof c.id === 'string' && typeof c.name === 'string' && Array.isArray(c.items))
      .map(c => ({id: c.id.slice(0, 80), name: c.name.slice(0, 60), items: c.items.filter(v => v && validID(v.id)).slice(0, 200).map(savedItem)}));
  } catch {
    toast('Your saved collections could not be read. Browser storage may be unavailable.');
    return [{id: 'watch-later', name: 'Watch later', items: []}];
  }
}
async function persist(next) {
  if (collectionSaving) return false;
  collectionSaving = true; collectionLoadVersion++; updateSaveButtons();
  try {
    if (accountRequired) {
      if (!account || !collectionsReady) { toast('Reload your collections before saving changes.'); return false; }
      try {
        const result = await api('/api/collections', {method: 'PUT', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({revision: collectionRevision, items: next})});
        collectionRevision = result.revision; collections = result.items; updateSavedCount();
        collectionChannel?.postMessage({owner: account.id}); return true;
      } catch (error) {
        if (error.status === 409) {
          collectionsReady = false;
          collectionSaving = false;
          try { await refreshCollections(); if (view === 'saved') renderSaved(); } catch {}
        }
        toast(error.message); return false;
      }
    }
    try { localStorage.setItem(storageKey, JSON.stringify(next)); collections = next; updateSavedCount(); return true; }
    catch { toast('This could not be saved. Check the available browser storage.'); return false; }
  } finally { collectionSaving = false; updateSaveButtons(); }
}
function updateSavedCount() { $('#saved-count').textContent = String(collections.reduce((n, c) => n + c.items.length, 0)); updateSaveButtons(); }
function refreshCollectionOptions() {
  const selected = $('#collection-select').value || currentCollection;
  $('#collection-select').replaceChildren(...collections.map(c => { const o = el('option', '', c.name); o.value = c.id; return o; }));
  if (collections.some(c => c.id === selected)) $('#collection-select').value = selected;
}
function openSave(item = null) {
  if (!collectionsReady) { toast('Your collections could not load. Refresh this page before saving.'); return; }
  pendingSave = item ? savedItem(item) : null;
  $('#save-heading').textContent = item ? 'Save to collection' : 'New collection';
  $('#save-description').textContent = item ? (item.guest || item.title) : 'Enter a collection name.';
  $('#collection-select').replaceChildren(); refreshCollectionOptions();
  $('#collection-select').disabled = !item;
  $('#collection-name').value = ''; $('#collection-name').required = !item || !collections.length;
  $('#save-error').textContent = ''; $('#confirm-save').replaceChildren(document.createTextNode(item ? 'Save to collection ' : 'Create collection '), icon(item ? 'save' : 'plus'));
  lastFocused = document.activeElement; $('#save-dialog').showModal();
  syncCollections();
  if (!item) $('#collection-name').focus();
}
$('#save-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (collectionSaving) return;
  const name = $('#collection-name').value.trim();
  let next = collections.map(c => ({...c, items: [...c.items]}));
  let collection = name ? next.find(c => c.name.toLowerCase() === name.toLowerCase()) : next.find(c => c.id === $('#collection-select').value);
  if (name && !collection) {
    if (next.length >= 100) { $('#save-error').textContent = 'You can keep up to 100 collections.'; return; }
    collection = {id: crypto.randomUUID(), name, items: []}; next.push(collection);
  }
  if (!collection || (!pendingSave && !name)) { $('#save-error').textContent = 'Give your collection a name.'; return; }
  if (pendingSave) {
    if (collection.items.some(i => itemKey(i) === itemKey(pendingSave))) { $('#save-error').textContent = 'This is already in that collection.'; return; }
    if (collection.items.length >= 200) { $('#save-error').textContent = 'This collection is full. Create another collection to keep more ideas.'; return; }
    collection.items.push(pendingSave);
  }
  $('#confirm-save').disabled = true;
  let saved;
  try { saved = await persist(next); } finally { $('#confirm-save').disabled = false; }
  if (!saved) return;
  currentCollection = collection.id; closeDialog('save-dialog');
  toast(pendingSave ? `Saved to ${collection.name}.` : `${collection.name} is ready.`);
  if (view === 'saved') renderSaved();
});
async function removeSaved(collectionId, key) {
  const next = collections.map(c => c.id === collectionId ? {...c, items: c.items.filter(i => itemKey(i) !== key)} : c);
  if (await persist(next)) { renderSaved(); toast('Removed from this collection.'); }
}
function closeDialog(id) { $('#' + id).close(); }
function stopVideo() { $('#video-container').replaceChildren(); $('#watch-container').replaceChildren(); $('#watch-panel').hidden = true; }
function navigate(next, options = {}) {
  if (!['discover', 'conversations', 'saved', 'answer'].includes(next)) next = 'discover';
  if (view !== next) { stopVideo(); if ($('#video-dialog').open) $('#video-dialog').close(); }
  view = next; navigationVersion++;
  document.querySelectorAll('.view').forEach(section => { section.hidden = section.id !== `${view}-view`; });
  document.querySelectorAll('[data-view]').forEach(node => {
    if (node.closest('.main-nav') && node.dataset.view === view) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
  const route = options.route || (view === 'answer' ? answerRoute : view);
  if (options.history !== false && location.hash !== '#' + route) history[options.replace ? 'replaceState' : 'pushState'](null, '', '#' + route);
  const destination = view === 'answer' ? $('#answer-composer-body') : $('#home-composer');
  destination.append($('#question-form'), $('#availability-note'));
  $('#question').placeholder = view === 'answer' ? 'What else are you trying to figure out?' : 'What are you trying to figure out?';
  $('#question-label').textContent = view === 'answer' ? 'Ask another question' : 'What are you trying to figure out?';
  if (view === 'conversations') renderCatalog();
  if (view === 'saved') { renderSaved(); syncCollections(); historyOffset = 0; loadHistory(); }
  updateResume();
  updateConnection();
  if (options.scroll !== false) window.scrollTo({top: 0, behavior: 'instant'});
}
function openCatalog(search = '', selectedTopic = '') {
  query = search; topic = selectedTopic; visibleCount = 12;
  $('#catalog-search').value = search; navigate('conversations');
}
function mediaFrame(item) {
  const id = videoID(item); if (!validID(id)) return null;
  const params = new URLSearchParams({autoplay: '1', rel: '0'});
  if (Number.isFinite(item.start)) params.set('start', String(Math.floor(Math.max(0, item.start))));
  if (Number.isFinite(item.end) && item.end > (item.start || 0)) params.set('end', String(Math.ceil(item.end)));
  const frame = el('iframe');
  // YouTube requires the embedding origin even when the page uses no-referrer.
  frame.referrerPolicy = 'strict-origin-when-cross-origin';
  frame.src = `https://www.youtube-nocookie.com/embed/${id}?${params}`;
  frame.title = item.title || 'Figuring Out conversation'; frame.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen'; frame.allowFullscreen = true;
  return frame;
}
function play(item, dock = view === 'answer') {
  const frame = mediaFrame(item); if (!frame) { toast('This video link is unavailable.'); return; }
  lastFocused = document.activeElement;
  if (dock) {
    $('#video-container').replaceChildren(); $('#watch-container').replaceChildren(frame); $('#watch-panel').hidden = false;
    watchDetails(item);
    $('#watch-panel').scrollIntoView({behavior: 'instant', block: 'nearest'});
  } else {
    $('#watch-container').replaceChildren(); $('#watch-panel').hidden = true;
    $('#video-title').textContent = `${item.title}${clipKey(item) ? ' · Clip ' + clipRange(item) : ''}`;
    $('#video-external').href = fullVideoURL(item);
    $('#video-container').replaceChildren(frame);
    $('#video-dialog').showModal();
  }
}
function watchDetails(item) {
  $('#watch-details').replaceChildren(el('h3', '', item.title || findVideo(videoID(item))?.title),
    el('p', '', clipKey(item) ? `Clip ${clipRange(item)} · Stops at ${timeLabel(Math.ceil(item.end))}` : 'Full video'));
}
function episodeArt(video) {
  const node = button('', 'episode-art', () => play(video)); node.setAttribute('aria-label', `Watch ${video.guest || video.display_title || video.title}`);
  const circle = el('span', 'play-circle'); circle.append(icon('play')); node.append(imageFor(video), circle);
  if (video.episode) node.append(el('span', 'episode-number', `EP. ${video.episode}`));
  return node;
}
function episodeCard(video, className = 'catalog-card', collectionId = '') {
  const article = el('article', className); article.append(episodeArt(video));
  const copy = el('div', 'episode-copy');
  copy.append(el('p', 'episode-meta', video.kind === 'moment' ? `Saved clip · ${clipRange(video)}` : (video.topic || 'Figuring Out')));
  const heading = el('div', 'episode-copy-heading');
  heading.append(el('h3', '', video.display_title || video.title), saveButton(video, `Save ${video.guest || video.title}`));
  copy.append(heading, el('p', 'episode-guest', video.guest ? `${video.guest}${video.role ? ' · ' + video.role : ''}` : `Figuring Out${video.episode ? ' · Episode ' + video.episode : ''}`));
  if (collectionId) copy.append(button('Remove from collection', 'remove-save', () => removeSaved(collectionId, itemKey(video))));
  article.append(copy); return article;
}
function episodeRow(video) {
  const row = el('article', 'episode-row'), copy = el('div');
  copy.append(el('p', 'episode-meta', video.topic), el('h3', '', video.display_title || video.title), el('p', 'episode-guest', video.guest || 'Figuring Out'));
  row.append(episodeArt(video), copy, saveButton(video, `Save ${video.guest || video.title}`)); return row;
}
function renderHome() {
  $('#home-topics').replaceChildren(...topics.map((name, i) => {
    const node = button('', 'topic-button', () => openCatalog('', name));
    node.append(el('span', 'topic-number', String(i + 1).padStart(2, '0')), el('strong', '', name), icon('up')); return node;
  }));
  const lead = findVideo('46P1rL0rzPE'); const list = el('div', 'editorial-list');
  ['PXMyK7JxGOk', 'sGpc8-f2e8U', '4Vz6L8B73i4'].map(findVideo).filter(Boolean).forEach(v => list.append(episodeRow(v)));
  $('#editorial-picks').replaceChildren(...(lead ? [episodeCard(lead, 'editorial-lead'), list] : [list]));
}
function matches(video) {
  if (topic && video.topic !== topic) return false;
  if (!query.trim()) return true;
  const tokens = query.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
  const stop = new Set('the a an how can i do does what is are to of on for my me and with conversations videos say about'.split(' '));
  const terms = tokens.filter(t => !stop.has(t) && t.length > 1);
  const text = [video.title, video.topic, video.guest].join(' ').toLowerCase();
  return terms.length ? terms.some(term => text.includes(term)) : text.includes(query.toLowerCase());
}
function renderCatalog() {
  $('#catalog-topics').replaceChildren(...['All conversations', ...topics].map((name, i) => {
    const node = button(name, '', () => { topic = i ? name : ''; visibleCount = 12; renderCatalog(); });
    node.setAttribute('aria-pressed', String(topic === (i ? name : ''))); return node;
  }));
  const rows = catalog.filter(matches);
  $('#catalog-count').textContent = `${rows.length} conversation${rows.length === 1 ? '' : 's'}${query ? ' matching episode titles and topics' : topic ? ' · ' + topic : ' in the catalog'}`;
  $('#clear-filters').hidden = !topic && !query;
  $('#catalog-grid').replaceChildren(...rows.slice(0, visibleCount).map(v => episodeCard(v)));
  if (!rows.length) {
    const empty = el('div', 'empty-content'); empty.append(el('h3', '', 'Try a different starting point.'), el('p', '', 'No episode titles or topics match this search. Try a guest name, a broader topic, or clear the filters.'), button('Explore all conversations', 'text-link', () => openCatalog(), 'arrow'));
    $('#catalog-grid').append(empty);
  }
  $('#load-more').hidden = rows.length <= visibleCount;
}
function renderSaved() {
  if (!collections.some(c => c.id === currentCollection)) currentCollection = collections[0]?.id || '';
  $('#collection-tabs').replaceChildren(...collections.map(c => {
    const node = button(`${c.name} · ${c.items.length}`, '', () => { currentCollection = c.id; renderSaved(); });
    node.setAttribute('aria-pressed', String(c.id === currentCollection)); return node;
  }));
  const collection = collections.find(c => c.id === currentCollection);
  $('#saved-grid').replaceChildren(...(collection?.items || []).map(item => episodeCard({...findVideo(item.id), ...item}, 'catalog-card', collection.id)));
  if (!collection?.items.length) {
    const empty = el('div', 'empty-content'); empty.append(el('h3', '', collectionsReady ? 'No saved conversations' : 'Collections unavailable'), el('p', '', collectionsReady ? 'Use the bookmark button on a conversation or clip to save it here.' : 'Your collections could not load. Reload this page to try again.'), button('Browse conversations', 'text-link', () => openCatalog(), 'arrow')); $('#saved-grid').append(empty);
  }
  updateSaveButtons();
}
async function loadHistory(offset = 0) {
  const version = ++historyVersion;
  $('#history-more').disabled = true;
  try {
    const result = await api('/api/responses?offset=' + offset);
    if (version !== historyVersion || view !== 'saved') return;
    if (!offset) $('#response-history').replaceChildren();
    result.items.forEach(item => {
      const row = el('article', 'history-row');
      const open = button('', '', () => openHistory(item.id));
      open.append(el('h3', '', item.question || 'Question'), el('p', '', `${new Date(item.created_at).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'})} · ${item.status === 'error' ? 'Request could not finish' : item.status.replaceAll('_', ' ')}`));
      row.append(open); $('#response-history').append(row);
    });
    if (!result.total) $('#response-history').append(el('p', 'section-note', 'Your questions will appear here after you ask the connected archive.'));
    historyOffset = offset + result.items.length;
    $('#history-more').hidden = historyOffset >= result.total;
  } catch {
    if (version !== historyVersion || view !== 'saved') return;
    if (offset) toast('Older questions could not load. Please try again.');
    else $('#response-history').replaceChildren(el('p', 'section-note', 'Past questions are unavailable right now. Try again when the local library is connected.'));
  } finally { if (version === historyVersion) $('#history-more').disabled = false; }
}
async function openHistory(id, options = {}) {
  if (busy) { toast('Let this question finish before opening another.'); return; }
  const version = ++navigationVersion;
  try {
    const record = await api('/api/responses/' + id);
    if (version !== navigationVersion || busy) return;
    lastQuestion = {question: record.question, sourceID: record.source_id || ''};
    answerRoute = 'answer/' + id;
    beginAnswer(record.question, {...options, route: answerRoute}); renderAnswer(record.response);
    if (!record.response.error) $('#request-status').textContent = `Saved response · ${new Date(record.created_at).toLocaleString()}`;
  } catch (error) { toast(error.message); }
}
function followRoute() {
  const route = location.hash.slice(1);
  if (route.startsWith('moment-')) return;
  if (/^answer\/[a-f0-9]{32}$/.test(route)) {
    if (route === answerRoute && $('#asked-question').textContent) navigate('answer', {history: false});
    else if (busy) { toast('Your current question is still being checked.'); navigate('answer', {replace: true}); }
    else openHistory(route.split('/')[1], {history: false});
  } else if (route === 'answer' && $('#asked-question').textContent) navigate('answer', {replace: true});
  else navigate(['discover', 'conversations', 'saved'].includes(route) ? route : 'discover', {replace: true});
}
function updateResume() {
  $('#resume-question').hidden = view === 'answer' || !$('#asked-question').textContent;
  $('#resume-label').textContent = busy ? 'Your question is being checked. Return to the conversation' : 'Return to your last question';
}
function setProgress(text, error = false, loading = false) { $('#request-status').textContent = text; $('#request-status').className = 'request-status' + (error ? ' error' : '') + (loading ? ' loading' : ''); }
function generationPhase(phase) {
  if (!['search', 'compose'].includes(phase)) return;
  document.querySelectorAll('#answer-progress [data-phase]').forEach(node => {
    const active = node.dataset.phase === phase;
    const complete = phase === 'compose' && node.dataset.phase === 'search';
    if (active) node.setAttribute('aria-current', 'step');
    else node.removeAttribute('aria-current');
    node.querySelector('.phase-state').textContent = active ? 'In progress' : complete ? 'Done' : 'Waiting';
  });
}
function beginAnswer(question, options = {}) {
  navigate('answer', options); $('#asked-question').textContent = question; $('#answer').replaceChildren(); $('#moments').replaceChildren(); $('#moments-section').hidden = true;
  $('#retry-question').hidden = true;
  $('#answer-scope').textContent = lastQuestion?.sourceID ? 'Searched in: ' + (findVideo(lastQuestion.sourceID)?.title || 'Selected conversation') : 'Searched across all conversations';
  $('#watch-panel').hidden = true; $('#watch-container').replaceChildren(); setProgress('');
}
function momentCard(citation, index, guide) {
  const node = el('article', 'moment'); node.id = `moment-${index + 1}`; node.tabIndex = -1;
  const top = el('div', 'moment-topline'), copy = el('div');
  copy.append(el('h3', '', citation.title || findVideo(videoID(citation))?.title), el('p', '', `Clip ${index + 1} · ${clipRange(citation)}`));
  top.append(imageFor(citation), copy, saveButton({...citation, kind: 'moment'}, 'Save this moment')); node.append(top);
  const description = guide?.summary || guide?.why_relevant;
  if (description) node.append(el('p', 'moment-copy', description));
  if (guide?.limitation) node.append(el('p', 'moment-limit', guide.limitation));
  const actions = el('div', 'moment-actions');
  const playButton = button('Play clip', '', () => play(citation, true), 'play');
  playButton.setAttribute('aria-label', `Play clip ${index + 1}: ${clipRange(citation)}`);
  actions.append(playButton, external('Full video', fullVideoURL(citation))); node.append(actions); return node;
}
function renderMoments(items) {
  $('#moments-section').hidden = !items.length;
  $('#moments-heading').textContent = 'Related clips';
  $('#moment-count').textContent = `${items.length} clip${items.length === 1 ? '' : 's'}`;
  $('#moments-note').textContent = 'Play a clip here, or open the full video on YouTube.';
  $('#moments').replaceChildren(...items.map((item, i) => momentCard(item.citation || item, i, item)));
  $('#watch-panel').hidden = true; $('#watch-container').replaceChildren();
}
function renderAnswer(answer) {
  $('#answer').replaceChildren();
  $('#retry-question').hidden = true;
  if (/^[a-f0-9]{32}$/.test(answer.record_id || '')) {
    answerRoute = 'answer/' + answer.record_id;
    if (view === 'answer') history.replaceState(null, '', '#' + answerRoute);
  }
  if (answer.error) {
    renderMoments([]);
    $('#retry-question').hidden = false;
    $('#answer').append(el('p', 'answer-message error', answer.error));
    setProgress('The request could not finish.', true); return;
  }
  const noEvidence = ['insufficient_evidence', 'invalid_evidence', 'needs_clarification'].includes(answer.status);
  const points = noEvidence ? [] : answer.points || [];
  const moments = [], seen = new Set();
  const addMoment = item => {
    const citation = item?.citation || item, key = clipKey(citation);
    if (key && !seen.has(key)) { seen.add(key); moments.push({...item, citation}); }
  };
  if (!noEvidence) (answer.recommendations || []).forEach(addMoment);
  points.forEach(p => (p.citations || []).forEach(c => addMoment({citation: c, summary: c.summary})));
  if (points.length) {
    const prose = el('div', 'answer-prose');
    points.forEach(point => {
      const paragraph = el('p', '', point.text), linked = new Set();
      (point.citations || []).forEach(c => {
        const number = moments.findIndex(m => clipKey(m.citation) === clipKey(c)) + 1;
        if (number < 1 || linked.has(number)) return;
        const link = button(String(number), 'citation-link', () => play(c, true));
        link.setAttribute('aria-label', `Play clip ${number}: ${clipRange(c)}`);
        paragraph.append(link); linked.add(number);
      });
      prose.append(paragraph);
    });
    $('#answer').append(prose);
  } else {
    $('#answer').append(el('p', 'answer-message', answer.message || 'There isn’t enough verified evidence for an answer. Try a more specific question.'));
    $('#retry-question').hidden = !(['provider_error', 'invalid_evidence'].includes(answer.reply_status) || answer.status === 'invalid_evidence');
  }
  renderMoments(moments);
  setProgress(answer.recording_error || (answer.record_id ? 'Saved to your past questions.' : ''), Boolean(answer.recording_error));
}
async function ask(question, selectedTopic = '', options = {}) {
  if (busy || !question.trim()) return;
  question = question.trim();
  if (question.length > 6000) { toast('Keep your question under 6,000 characters.'); return; }
  if (!canAnswer()) {
    if (view === 'answer') { toast('The answer archive is unavailable. Your draft is kept here; reconnect the library to ask it.'); return; }
    openCatalog(selectedTopic ? '' : question, selectedTopic);
    toast('Showing episode titles and topics. Answer search needs the connected caption archive.'); return;
  }
  const sourceID = options.sourceID ?? $('#video-scope').value;
  lastQuestion = {question, sourceID}; answerRoute = 'answer';
  busy = true; $('#ask-button').disabled = true;
  if (!options.retry) { $('#question').value = ''; $('#question').style.height = '44px'; }
  beginAnswer(question); setProgress('Searching the original conversations…', false, true);
  updateConnection(); $('#asked-question').focus({preventScroll: true});
  generationPhase('search'); $('#answer-progress').hidden = false;
  const startedAt = Date.now();
  const elapsed = () => { $('#answer-elapsed').textContent = `Elapsed ${timeLabel((Date.now() - startedAt) / 1000)}`; };
  elapsed(); const elapsedTimer = setInterval(elapsed, 1000);
  const controller = new AbortController();
  let reader, timedOut = false;
  const slowTimer = setTimeout(() => setProgress('This is taking longer than usual. Still preparing your answer…', false, true), 30000);
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 300000);
  $('#answer').setAttribute('aria-busy', 'true');
  try {
    const payload = {question}; if (sourceID) payload.source_id = sourceID;
    const response = await fetch('/api/ask/stream', {method: 'POST', headers: accountHeaders({'Content-Type': 'application/json'}), body: JSON.stringify(payload), signal: controller.signal});
    if (!response.ok) { const data = await response.json(); throw new Error(data.error || 'This question could not be sent.'); }
    if (!response.body) throw new Error('The response stream is unavailable in this browser.');
    reader = response.body.getReader();
    const decoder = new TextDecoder(); let buffer = '', finished = false;
    const consume = line => {
      if (finished || !line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === 'stage' && typeof event.message === 'string') {
        setProgress(event.message, false, true); generationPhase(event.phase);
      }
      // Older servers may send raw excerpts. Only the final response can show clips.
      if (event.type === 'answer') { renderAnswer(event.response); finished = true; }
    };
    while (!finished) {
      const part = await reader.read(); buffer += decoder.decode(part.value || new Uint8Array(), {stream: !part.done});
      let newline;
      while (!finished && (newline = buffer.indexOf('\n')) >= 0) { consume(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1); }
      if (part.done) { consume(buffer); break; }
    }
    if (!finished) throw new Error('The connection ended before your answer was ready. Please retry your question.');
  } catch (error) {
    $('#answer').replaceChildren(); renderMoments([]);
    $('#retry-question').hidden = false;
    const message = timedOut ? 'Your answer is taking too long. Check your past questions shortly, or retry.'
      : error instanceof SyntaxError ? 'The response could not be read. Please retry your question.'
      : error instanceof TypeError ? 'The connection was interrupted. Please retry your question.'
      : error.message || 'This request could not finish. Please try again.';
    setProgress(message, true);
  } finally {
    clearTimeout(slowTimer); clearTimeout(timeout); clearInterval(elapsedTimer);
    $('#answer-progress').hidden = true;
    if (reader) reader.cancel().catch(() => {});
    controller.abort();
    $('#answer').setAttribute('aria-busy', 'false');
    busy = false; $('#ask-button').disabled = false; updateConnection(); updateResume();
    if (view === 'saved') { historyOffset = 0; loadHistory(); }
  }
}
function updateConnection() {
  $('#answer-composer').hidden = busy;
  $('#ask-again').hidden = busy;
  $('#question-form').hidden = busy;
  $('#availability-note').hidden = busy;
  const videos = readyVideos(), selected = $('#video-scope').value;
  if (!busy) {
    const first = el('option', '', 'All conversations'); first.value = '';
    $('#video-scope').replaceChildren(first, ...videos.map(v => { const o = el('option', '', v.title); o.value = v.id; return o; }));
    if (videos.some(v => v.id === selected)) $('#video-scope').value = selected;
  }
  $('#search-mode').textContent = canAnswer() ? 'Ask the archive' : view === 'answer' ? 'Archive unavailable' : 'Browse episodes';
  $('#ask-button').setAttribute('aria-label', view === 'answer' ? 'Ask another question' : canAnswer() ? 'Ask the archive' : 'Browse matching episodes');
  $('#availability-note').textContent = canAnswer() ? 'Answers with clips from the original conversations.' : 'Explore episodes now. Answers become available when the caption archive is connected.';
  if (view === 'answer') $('#availability-note').textContent = 'Each question searches independently. Include the names or topics you mean.';
  if (view === 'answer' && !busy && !canAnswer()) $('#availability-note').textContent = 'The answer archive is unavailable. Your draft stays here while the library reconnects.';
  $('#retry-question').disabled = busy;
  $('#archive-status').textContent = `${catalog.length} episodes in this catalog. ${videos.length} conversations currently searchable.`;
  const missing = [];
  if (!videos.length) missing.push('Restore the original data directory to make caption search available.');
  if (!status?.credentials?.answers) missing.push('Configure OPENAI_API_KEY on the server for checked answers.');
  if (!status?.credentials?.indexing && status?.backend === 'supermemory') missing.push('Configure SUPERMEMORY_API_KEY for semantic retrieval; local keyword retrieval can still use restored captions.');
  $('#connection-details').textContent = status ? missing.join(' ') || 'The archive is connected and ready for questions.' : 'The local server could not be reached. Check that it is running, then refresh.';
  if (accountRequired) $('#connection-details').textContent = canAnswer() ? 'The archive is ready for questions.' : 'The archive is temporarily unavailable. Please try again shortly.';
}
async function refreshStatus() {
  const version = ++statusVersion;
  try {
    const next = await api('/api/status');
    if (next.read_only && next.counts?.ready > next.sources.length) {
      const sources = [...next.sources], seen = new Set(sources.map(v => v.id));
      while (sources.length < next.counts.ready) {
        const page = await api('/api/videos?offset=' + sources.length + '&status=ready');
        const extra = page.sources.filter(v => !seen.has(v.id));
        if (!extra.length) break;
        extra.forEach(v => { seen.add(v.id); sources.push(v); });
        if (version !== statusVersion) return;
      }
      next.sources = sources;
    }
    if (version !== statusVersion) return;
    status = next;
  } catch { if (version !== statusVersion) return; status = null; }
  updateConnection();
}
function bind() {
  document.querySelectorAll('[data-view]').forEach(node => node.addEventListener('click', () => navigate(node.dataset.view)));
  document.querySelectorAll('[data-play]').forEach(node => node.addEventListener('click', () => { const v = findVideo(node.dataset.play); if (v) play(v); }));
  document.querySelectorAll('[data-save]').forEach(node => node.addEventListener('click', () => { const v = findVideo(node.dataset.save); if (v) openSave(v); }));
  document.querySelectorAll('[data-question]').forEach(node => node.addEventListener('click', () => { $('#question').value = node.dataset.question; ask(node.dataset.question, node.dataset.topic); }));
  document.querySelectorAll('[data-close]').forEach(node => node.addEventListener('click', () => closeDialog(node.dataset.close)));
  $('#question-form').addEventListener('submit', event => { event.preventDefault(); ask($('#question').value); });
  $('#question').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#question-form').requestSubmit(); } });
  $('#question').addEventListener('input', () => { $('#question').style.height = '44px'; $('#question').style.height = Math.min($('#question').scrollHeight, 130) + 'px'; });
  $('#catalog-search-form').addEventListener('submit', event => { event.preventDefault(); query = $('#catalog-search').value; visibleCount = 12; renderCatalog(); });
  $('#catalog-search').addEventListener('input', () => { query = $('#catalog-search').value; visibleCount = 12; renderCatalog(); });
  $('#clear-filters').addEventListener('click', () => openCatalog());
  $('#load-more').addEventListener('click', () => { visibleCount += 12; renderCatalog(); });
  $('#new-collection').addEventListener('click', () => openSave());
  $('#history-more').addEventListener('click', () => loadHistory(historyOffset));
  $('#ask-again').addEventListener('click', () => { if (busy) return; $('#question').focus({preventScroll: true}); $('#answer-composer').scrollIntoView({block: 'center', behavior: 'instant'}); });
  $('#retry-question').addEventListener('click', () => { if (lastQuestion) ask(lastQuestion.question, '', {sourceID: lastQuestion.sourceID, retry: true}); });
  $('#return-to-answer').addEventListener('click', () => navigate('answer'));
  $('#close-watch').addEventListener('click', () => { $('#watch-container').replaceChildren(); $('#watch-panel').hidden = true; lastFocused?.focus({preventScroll: true}); });
  $('#close-video').addEventListener('click', () => closeDialog('video-dialog'));
  $('#video-external').addEventListener('click', () => { stopVideo(); closeDialog('video-dialog'); });
  $('#video-dialog').addEventListener('close', () => { $('#video-container').replaceChildren(); lastFocused?.focus(); });
  $('#save-dialog').addEventListener('close', () => lastFocused?.focus());
  $('#about-button').addEventListener('click', () => $('#about-dialog').showModal());
  window.addEventListener('hashchange', followRoute);
  window.addEventListener('storage', event => { if (!accountRequired && (event.key === storageKey || event.key === null)) { collections = loadCollections(); updateSavedCount(); if (view === 'saved') renderSaved(); if ($('#save-dialog').open) refreshCollectionOptions(); } });
  collectionChannel?.addEventListener('message', event => { if (event.data?.owner === account?.id) syncCollections(true); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) syncCollections(true); });
  $('#account-button').addEventListener('click', async () => {
    if (busy) { toast('Let your current answer finish before signing out.'); return; }
    try {
      const result = await api('/auth/logout', {method: 'POST'});
      // Remove account content before leaving, including when returning via browser history.
      document.body.replaceChildren(); location.replace(result.redirect);
    } catch (error) { toast(error.message); }
  });
  window.addEventListener('pageshow', event => { if (accountRequired && event.persisted) location.reload(); });
  window.addEventListener('focus', async () => {
    if (!accountRequired || !account) return;
    try {
      const fresh = await api('/api/account');
      if (fresh.id !== account.id || fresh.csrf !== account.csrf) { location.reload(); return; }
      syncCollections(true);
    }
    catch (error) { if (error.status === 401) location.reload(); }
  });
}
async function refreshCollections() {
  if (collectionSaving) return;
  const version = ++collectionLoadVersion;
  const result = await api('/api/collections');
  // A delayed read must never replace a newer save or another refresh.
  if (version !== collectionLoadVersion || collectionSaving || result.revision < collectionRevision) return;
  const changed = !collectionsReady || result.revision !== collectionRevision;
  collections = result.items; collectionRevision = result.revision; collectionsReady = true; updateSavedCount();
  if (changed && view === 'saved') renderSaved();
  if (changed && $('#save-dialog').open) refreshCollectionOptions();
}
function syncCollections(quiet = false) {
  if (!accountRequired || !account || collectionSaving) return;
  return refreshCollections().catch(() => { if (!quiet) toast('Collections could not refresh. Try again shortly.'); });
}
async function init() {
  bind();
  if (accountRequired) {
    try {
      account = await api('/api/account');
      $('#account-button').hidden = guestMode; $('#account-button').title = guestMode ? '' : 'Signed in as ' + account.email;
      $('#collection-storage-note').textContent = guestMode
        ? 'Saved for this browser for up to 30 days. Clearing cookies ends access.'
        : 'Your saved conversations and moments, available across your devices.';
      $('#history-storage-note').textContent = guestMode ? 'Saved for this browser' : 'Visible only to your account';
      $('#save-dialog .dialog-note').textContent = guestMode ? 'Saved for this browser. No account needed.' : 'Saved to your account.';
      await refreshCollections().catch(() => toast('Your collections could not load. Reload this page before saving.'));
    } catch (error) {
      if (error.status === 401 && !guestMode) { location.replace('/auth/login'); return; }
      toast(guestMode ? 'Your browser session could not load. Allow cookies and refresh before asking or saving.'
        : 'Your account could not load. Refresh before asking or saving.'); return;
    }
  } else { collections = loadCollections(); updateSavedCount(); }
  try {
    const data = await api('/catalog.json'); catalog = data.episodes.filter(v => validID(v.id));
    renderHome();
  } catch { $('#editorial-picks').replaceChildren(el('p', 'section-note', 'The episode catalog could not load. Refresh to try again.')); }
  await refreshStatus();
  followRoute();
  statusTimer = setInterval(() => {
    if (!document.hidden) { if (!busy) refreshStatus(); syncCollections(true); }
  }, 15000);
}
init();
