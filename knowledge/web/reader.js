'use strict';
const $ = selector => document.querySelector(selector);
const svgNS = 'http://www.w3.org/2000/svg';
const topics = ['Mind & body', 'Business & money', 'Work & ambition', 'Life & perspective', 'World & society'];
const storageKey = 'figuring-out.collections.v1';
let catalog = [], status = null, view = 'discover', topic = '', query = '', visibleCount = 12;
let collections = [], currentCollection = '', pendingSave = null, busy = false, historyOffset = 0;
let currentMoments = [], toastTimer, statusTimer, lastFocused = null;

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
  const a = el('a', 'text-link', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.append(icon('up')); return a;
}
function videoID(item) { return item?.source_id || item?.id || ''; }
function validID(id) { return typeof id === 'string' && /^[A-Za-z0-9_-]{11}$/.test(id); }
function canonical(item) {
  const id = videoID(item);
  return validID(id) ? `https://www.youtube.com/watch?v=${id}${Number.isFinite(item.start) ? '&t=' + Math.floor(Math.max(0, item.start)) + 's' : ''}` : '';
}
function timeLabel(value) { const s = Math.floor(Math.max(0, Number(value) || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function findVideo(id) { return catalog.find(v => v.id === id) || readyVideos().find(v => v.id === id); }
function readyVideos() { return (status?.sources || []).filter(v => v.state === 'ready' || v.status === 'ready'); }
function canAnswer() { return Boolean(status?.credentials?.answers && readyVideos().length); }
function toast(message) {
  clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
}
async function api(path) {
  const response = await fetch(path); const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The library could not be reached. Please try again.');
  return result;
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
function itemKey(item) { return `${videoID(item)}:${item.kind === 'moment' ? Number(item.start) || 0 : 'episode'}`; }
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
      .map(c => ({id: c.id.slice(0, 80), name: c.name.slice(0, 60), items: c.items.filter(v => validID(v.id)).slice(0, 200).map(savedItem)}));
  } catch {
    toast('Your saved collections could not be read. Browser storage may be unavailable.');
    return [{id: 'watch-later', name: 'Watch later', items: []}];
  }
}
function persist(next) {
  try { localStorage.setItem(storageKey, JSON.stringify(next)); collections = next; updateSavedCount(); return true; }
  catch { toast('This could not be saved. Check the available browser storage.'); return false; }
}
function updateSavedCount() { $('#saved-count').textContent = String(collections.reduce((n, c) => n + c.items.length, 0)); }
function openSave(item = null) {
  pendingSave = item ? savedItem(item) : null;
  $('#save-heading').textContent = item ? 'Keep this perspective.' : 'A collection of your own.';
  $('#save-description').textContent = item ? (item.guest || item.title) : 'Give your ideas somewhere to grow.';
  $('#collection-select').replaceChildren(...collections.map(c => { const o = el('option', '', c.name); o.value = c.id; return o; }));
  $('#collection-select').disabled = !item;
  $('#collection-name').value = ''; $('#collection-name').required = !item || !collections.length;
  $('#save-error').textContent = ''; $('#confirm-save').replaceChildren(document.createTextNode(item ? 'Save to collection ' : 'Create collection '), icon(item ? 'save' : 'plus'));
  lastFocused = document.activeElement; $('#save-dialog').showModal();
  if (!item) $('#collection-name').focus();
}
$('#save-form').addEventListener('submit', event => {
  event.preventDefault();
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
  if (!persist(next)) return;
  currentCollection = collection.id; closeDialog('save-dialog');
  toast(pendingSave ? `Saved to ${collection.name}.` : `${collection.name} is ready.`);
  if (view === 'saved') renderSaved();
});
function removeSaved(collectionId, key) {
  const next = collections.map(c => c.id === collectionId ? {...c, items: c.items.filter(i => itemKey(i) !== key)} : c);
  if (persist(next)) { renderSaved(); toast('Removed from this collection.'); }
}
function closeDialog(id) { $('#' + id).close(); }
function stopVideo() { $('#video-container').replaceChildren(); $('#watch-container').replaceChildren(); $('#watch-panel').hidden = true; }
function navigate(next, options = {}) {
  if (!['discover', 'conversations', 'saved', 'answer'].includes(next)) next = 'discover';
  if (view !== next) { stopVideo(); if ($('#video-dialog').open) $('#video-dialog').close(); }
  view = next;
  document.querySelectorAll('.view').forEach(section => { section.hidden = section.id !== `${view}-view`; });
  document.querySelectorAll('[data-view]').forEach(node => {
    if (node.closest('.main-nav') && node.dataset.view === view) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
  if (location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
  if (view === 'conversations') renderCatalog();
  if (view === 'saved') { renderSaved(); historyOffset = 0; loadHistory(); }
  updateResume();
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
  const frame = el('iframe'); frame.src = `https://www.youtube-nocookie.com/embed/${id}?${params}`;
  frame.title = item.title || 'Figuring Out conversation'; frame.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen'; frame.allowFullscreen = true;
  return frame;
}
function play(item, dock = view === 'answer') {
  const frame = mediaFrame(item); if (!frame) { toast('This video link is unavailable.'); return; }
  if (dock) {
    $('#video-container').replaceChildren(); $('#watch-container').replaceChildren(frame); $('#watch-panel').hidden = false;
    watchDetails(item);
    if (innerWidth <= 800) $('#watch-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
  } else {
    $('#watch-container').replaceChildren(); $('#watch-panel').hidden = true;
    $('#video-title').textContent = item.title;
    $('#video-external').href = canonical(item);
    $('#video-container').replaceChildren(frame); lastFocused = document.activeElement;
    $('#video-dialog').showModal();
  }
}
function watchDetails(item) {
  const video = findVideo(videoID(item));
  $('#watch-details').replaceChildren(el('h3', '', video?.guest || item.title), el('p', '', item.time_range ? `Original conversation · ${item.time_range}` : 'Full conversation · Figuring Out'), external('Open on YouTube', canonical(item)));
}
function previewWatch(item) {
  if ($('#watch-container iframe')) return;
  const preview = button('', '', () => play(item, true)); preview.setAttribute('aria-label', 'Play supporting conversation');
  const circle = el('span', 'play-circle'); circle.append(icon('play'));
  const image = imageFor(item); image.loading = 'eager';
  preview.append(image, circle); $('#watch-container').replaceChildren(preview); $('#watch-panel').hidden = false; watchDetails(item);
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
  copy.append(el('p', 'episode-meta', video.kind === 'moment' ? `Saved moment · ${timeLabel(video.start)}` : (video.topic || 'Figuring Out')));
  const heading = el('div', 'episode-copy-heading');
  heading.append(el('h3', '', video.headline || video.display_title || video.title), iconButton(`Save ${video.guest || video.title}`, 'save', () => openSave(video)));
  copy.append(heading, el('p', 'episode-guest', video.guest ? `${video.guest}${video.role ? ' · ' + video.role : ''}` : `Figuring Out${video.episode ? ' · Episode ' + video.episode : ''}`));
  if (collectionId) copy.append(button('Remove from collection', 'remove-save', () => removeSaved(collectionId, itemKey(video))));
  article.append(copy); return article;
}
function episodeRow(video) {
  const row = el('article', 'episode-row'), copy = el('div');
  copy.append(el('p', 'episode-meta', video.topic), el('h3', '', video.headline || video.display_title), el('p', 'episode-guest', video.guest || 'Figuring Out'));
  row.append(episodeArt(video), copy, iconButton(`Save ${video.guest || video.title}`, 'save', () => openSave(video))); return row;
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
  const text = [video.title, video.topic, video.guest, video.headline].join(' ').toLowerCase();
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
    const empty = el('div', 'empty-content'); empty.append(el('h3', '', 'A place for your next good idea.'), el('p', '', 'Save conversations and original moments as you explore. They’ll be waiting here when you want to return.'), button('Find a conversation', 'text-link', () => openCatalog(), 'arrow')); $('#saved-grid').append(empty);
  }
}
async function loadHistory() {
  try {
    const result = await api('/api/responses?offset=' + historyOffset);
    if (!historyOffset) $('#response-history').replaceChildren();
    result.items.forEach(item => {
      const row = el('article', 'history-row');
      const open = button('', '', () => openHistory(item.id));
      open.append(el('h3', '', item.question || 'Question'), el('p', '', `${new Date(item.created_at).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'})} · ${item.status === 'error' ? 'Request could not finish' : item.status.replaceAll('_', ' ')}`));
      const download = el('a', '', 'Download'); download.href = '/api/responses/' + item.id; download.download = `figuring-out-${item.id}.json`; row.append(open, download); $('#response-history').append(row);
    });
    if (!result.total) $('#response-history').append(el('p', 'section-note', 'Your questions will appear here after you ask the connected archive.'));
    $('#history-more').hidden = historyOffset + result.items.length >= result.total;
  } catch { $('#response-history').replaceChildren(el('p', 'section-note', 'Past questions are unavailable right now. Try again when the local library is connected.')); }
}
async function openHistory(id) {
  if (busy) { toast('Let this question finish before opening another.'); return; }
  try {
    const record = await api('/api/responses/' + id);
    beginAnswer(record.question); renderAnswer(record.response);
    $('#request-status').textContent = `Saved response · ${new Date(record.created_at).toLocaleString()}`;
  } catch (error) { toast(error.message); }
}
function updateResume() {
  $('#resume-question').hidden = view === 'answer' || !$('#asked-question').textContent;
  $('#resume-label').textContent = busy ? 'Your question is being checked. Return to the conversation' : 'Return to your last question';
}
function setProgress(text, error = false, loading = false) { $('#request-status').textContent = text; $('#request-status').className = 'request-status' + (error ? ' error' : '') + (loading ? ' loading' : ''); }
function beginAnswer(question) {
  navigate('answer'); $('#asked-question').textContent = question; $('#answer').replaceChildren(); $('#moments').replaceChildren(); $('#moments-section').hidden = true;
  $('#watch-panel').hidden = true; $('#watch-container').replaceChildren(); currentMoments = []; setProgress('');
}
function momentCard(citation, index, guide) {
  const node = el('article', 'moment'); node.id = `moment-${index + 1}`;
  const top = el('div', 'moment-topline'), copy = el('div');
  const video = findVideo(videoID(citation));
  copy.append(el('h3', '', video?.guest || citation.title), el('p', '', `MOMENT ${String(index + 1).padStart(2, '0')} · ${citation.time_range || timeLabel(citation.start)}`));
  top.append(imageFor(citation), copy, iconButton('Save this moment', 'save', () => openSave({...citation, kind: 'moment'}))); node.append(top);
  if (guide?.summary) node.append(el('p', 'moment-copy', guide.summary));
  if (guide?.why_relevant) node.append(el('p', 'moment-copy', guide.why_relevant));
  if (guide?.limitation) node.append(el('p', 'moment-limit', guide.limitation));
  const evidence = el('details'); evidence.append(el('summary', '', guide ? 'Read the original excerpt' : 'Original excerpt · answer not yet checked'), el('blockquote', '', citation.quote)); node.append(evidence);
  const actions = el('div', 'moment-actions');
  const playButton = button(`Play from ${timeLabel(citation.start)}`, '', () => play(citation, true), 'play');
  actions.append(playButton, external('Full conversation', canonical(citation))); node.append(actions); return node;
}
function renderMoments(items, provisional = false) {
  currentMoments = items;
  $('#moments-section').hidden = !items.length;
  $('#moments-heading').textContent = provisional ? 'Original moments, ready to explore.' : 'Inside the conversations';
  $('#moment-count').textContent = `${items.length} moment${items.length === 1 ? '' : 's'}`;
  $('#moments-note').textContent = provisional ? 'These are retrieved source excerpts. Their relevance and the answer are still being checked.' : 'Hear each idea in the context of the original conversation.';
  $('#moments').replaceChildren(...items.map((item, i) => momentCard(item.citation || item, i, provisional ? null : item)));
  if (items.length) previewWatch(items[0].citation || items[0]);
}
function renderAnswer(answer) {
  $('#answer').replaceChildren();
  if (answer.error) {
    $('#answer').append(el('p', 'answer-message error', answer.error));
    if (currentMoments.length) $('#moments-note').textContent = 'The answer could not finish. These retrieved original excerpts remain available to explore; their relevance has not been verified.';
    setProgress('The request could not finish.', true); return;
  }
  const points = answer.points || [];
  const moments = answer.recommendations ? [...answer.recommendations] : [];
  if (!answer.recommendations) {
    const seen = new Set();
    points.forEach(p => (p.citations || []).forEach(c => { const key = `${videoID(c)}:${c.start}:${c.end}`; if (!seen.has(key)) { seen.add(key); moments.push({citation: c, summary: c.summary}); } }));
  }
  if (points.length) {
    const prose = el('div', 'answer-prose');
    points.forEach(point => {
      const paragraph = el('p', '', point.text), linked = new Set();
      (point.citations || []).forEach(c => {
        const number = moments.findIndex(m => videoID(m.citation) === videoID(c) && m.citation.start === c.start && m.citation.end === c.end) + 1;
        if (number < 1 || linked.has(number)) return;
        const link = el('a', 'citation-link', String(number)); link.href = '#moment-' + number; link.setAttribute('aria-label', `Read supporting moment ${number}`); paragraph.append(link); linked.add(number);
      });
      prose.append(paragraph);
    });
    $('#answer').append(prose);
  } else $('#answer').append(el('p', 'answer-message', answer.message || 'There isn’t enough verified evidence for an answer. Try a more specific question.'));
  renderMoments(moments);
  if (!moments.length) { $('#watch-panel').hidden = true; $('#watch-container').replaceChildren(); }
  setProgress(answer.recording_error || (answer.record_id ? 'Saved to your past questions. Every reference opens the original source.' : 'Based on the retrieved conversations.'), Boolean(answer.recording_error));
}
async function ask(question, selectedTopic = '') {
  if (busy || !question.trim()) return;
  question = question.trim();
  if (question.length > 6000) { toast('Keep your question under 6,000 characters.'); return; }
  if (!canAnswer()) {
    openCatalog(selectedTopic ? '' : question, selectedTopic);
    toast('Showing episode titles and topics. Answer search needs the connected caption archive.'); return;
  }
  busy = true; $('#ask-button').disabled = true; $('#video-scope').disabled = true;
  beginAnswer(question); setProgress('Searching the original conversations…', false, true);
  try {
    const payload = {question}; if ($('#video-scope').value) payload.source_id = $('#video-scope').value;
    const response = await fetch('/api/ask/stream', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    if (!response.ok) { const data = await response.json(); throw new Error(data.error || 'This question could not be sent.'); }
    if (!response.body) throw new Error('The response stream is unavailable in this browser.');
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '', finished = false;
    const consume = line => {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === 'stage') setProgress(event.message, false, true);
      if (event.type === 'excerpts') { renderMoments(event.excerpts, true); setProgress(event.message, false, true); }
      if (event.type === 'answer') { renderAnswer(event.response); finished = true; }
    };
    while (true) {
      const part = await reader.read(); buffer += decoder.decode(part.value || new Uint8Array(), {stream: !part.done});
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) { consume(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1); }
      if (part.done) { consume(buffer); break; }
    }
    if (!finished) throw new Error('The connection ended before the answer was ready. Your original excerpts are still available below.');
  } catch (error) {
    setProgress(error.message || 'This request could not finish. Please try again.', true);
    if (currentMoments.length) $('#moments-note').textContent = 'The answer did not finish. These retrieved excerpts are available to explore; their relevance has not been verified.';
  } finally {
    busy = false; $('#ask-button').disabled = false; $('#video-scope').disabled = false; updateConnection(); updateResume();
    if (view === 'saved') { historyOffset = 0; loadHistory(); }
  }
}
function updateConnection() {
  const videos = readyVideos(), selected = $('#video-scope').value;
  if (!busy) {
    const first = el('option', '', 'All conversations'); first.value = '';
    $('#video-scope').replaceChildren(first, ...videos.map(v => { const o = el('option', '', v.title); o.value = v.id; return o; }));
    if (videos.some(v => v.id === selected)) $('#video-scope').value = selected;
  }
  $('#search-mode').textContent = canAnswer() ? 'Ask the archive' : 'Browse episodes';
  $('#ask-button').setAttribute('aria-label', canAnswer() ? 'Ask the archive' : 'Browse matching episodes');
  $('#availability-note').textContent = canAnswer() ? 'Answers with original excerpts and links to the exact moments.' : 'Explore episodes now. Answers become available when the caption archive is connected.';
  $('#archive-status').textContent = `${catalog.length} episodes in this catalog. ${videos.length} conversations currently searchable.`;
  const missing = [];
  if (!videos.length) missing.push('Restore the original data directory to make caption search available.');
  if (!status?.credentials?.answers) missing.push('Configure OPENAI_API_KEY on the server for checked answers.');
  if (!status?.credentials?.indexing && status?.backend === 'supermemory') missing.push('Configure SUPERMEMORY_API_KEY for semantic retrieval; local keyword retrieval can still use restored captions.');
  $('#connection-details').textContent = status ? missing.join(' ') || 'The archive is connected and ready for questions.' : 'The local server could not be reached. Check that it is running, then refresh.';
}
async function refreshStatus() {
  try { status = await api('/api/status'); } catch { status = null; }
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
  $('#history-more').addEventListener('click', () => { historyOffset += 20; loadHistory(); });
  $('#ask-again').addEventListener('click', () => { if (busy) { toast('The current question is still being checked.'); return; } navigate('discover'); $('#question').focus(); });
  $('#return-to-answer').addEventListener('click', () => { navigate('answer'); if (currentMoments.length) previewWatch(currentMoments[0].citation || currentMoments[0]); });
  $('#close-watch').addEventListener('click', () => { $('#watch-container').replaceChildren(); $('#watch-panel').hidden = true; });
  $('#close-video').addEventListener('click', () => closeDialog('video-dialog'));
  $('#video-dialog').addEventListener('close', () => { $('#video-container').replaceChildren(); lastFocused?.focus(); });
  $('#save-dialog').addEventListener('close', () => lastFocused?.focus());
  $('#about-button').addEventListener('click', () => $('#about-dialog').showModal());
  window.addEventListener('hashchange', () => { const next = location.hash.slice(1); if (['discover', 'conversations', 'saved'].includes(next)) navigate(next); });
  window.addEventListener('storage', event => { if (event.key === storageKey) { collections = loadCollections(); updateSavedCount(); if (view === 'saved') renderSaved(); } });
}
async function init() {
  collections = loadCollections(); updateSavedCount(); bind();
  try {
    const data = await api('/catalog.json'); catalog = data.episodes.filter(v => validID(v.id));
    renderHome();
  } catch { $('#editorial-picks').replaceChildren(el('p', 'section-note', 'The episode catalog could not load. Refresh to try again.')); }
  await refreshStatus();
  navigate(['discover', 'conversations', 'saved'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'discover', {scroll: false});
  statusTimer = setInterval(() => { if (!document.hidden && !busy) refreshStatus(); }, 15000);
}
init();
