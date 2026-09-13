const $ = (selector) => document.querySelector(selector);
let currentStatus = null;
let requesting = false;
let channelPreview = null;
let findingChannel = false;
let videoOffset = 0;
let pageSources = [];
let videoFilter = '';
let historyOffset = 0;


function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error([result.error || 'The request could not be completed.', result.recording_error].filter(Boolean).join(' '));
  return result;
}

function requestMessage(message, error = false) {
  const node = $('#request-status');
  node.textContent = message;
  node.hidden = !message;
  node.className = error ? 'error' : '';
}

function updateControls() {
  const channels = currentStatus?.backend === 'supermemory';
  const readOnly = !currentStatus || currentStatus.read_only;
  const ready = channels ? currentStatus.counts.ready > 0 : currentStatus?.sources.some((source) => source.status === 'ready');
  $('#ask-button').disabled = requesting || !ready || !currentStatus?.credentials.answers;
  $('#video-scope').disabled = requesting;
  $('#channel-tools').hidden = readOnly || !channels;
  $('#video-filters').hidden = readOnly || !channels;
  $('#process').hidden = readOnly || channels;
  $('#add-source').hidden = Boolean(readOnly);
  $('#ingest-note').hidden = Boolean(readOnly);
  $('#find-channel').disabled = findingChannel;
  $('#find-channel').textContent = findingChannel ? 'Finding…' : 'Find';
  $('#process').disabled = Boolean(currentStatus?.job?.running) || !currentStatus?.credentials.transcription || !currentStatus?.links_count;
  $('#add-link').disabled = Boolean(currentStatus?.job?.running) || !currentStatus?.credentials.transcription;
  if (channels) $('#add-link').disabled = !currentStatus.credentials.indexing;
  $('#ask-button').firstChild.textContent = requesting ? 'Preparing reply… ' : 'Ask library ';
  $('#process').textContent = currentStatus?.job?.running ? 'Processing videos…' : ready ? 'Process / refresh videos' : 'Process videos';
}

function showSources(status) {
  if (status.backend === 'supermemory') { showChannelLibrary(status); return; }
  const fragment = document.createDocumentFragment();
  const jobs = new Map(status.job.items.map((item) => [item.id, item]));
  const known = new Set(status.sources.map((source) => source.id));
  const sources = [...status.sources, ...status.job.items.filter((item) => !known.has(item.id))];
  for (const source of sources) {
    const job = jobs.get(source.id);
    const item = element('article', 'source-item');
    const image = element('img', 'source-image');
    image.src = `https://i.ytimg.com/vi/${source.id}/mqdefault.jpg`;
    image.alt = '';
    image.loading = 'lazy';
    item.append(image);
    const link = element('a', '', source.title || job?.title || `YouTube · ${source.id}`);
    link.href = source.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    item.append(link);
    let state = source.status;
    let label = source.status === 'ready' ? `${source.chunks} passages · Ready` : 'Not processed yet';
    if (job && job.status !== 'ready') {
      state = job.status;
      label = job.status === 'error' ? job.error : job.stage;
    }
    item.append(element('div', `source-state ${state}`, label));
    fragment.append(item);
  }
  $('#source-list').replaceChildren(fragment);
  const ready = status.sources.filter((source) => source.status === 'ready').length;
  $('#source-count').textContent = String(sources.length);
  $('#collection-status').textContent = `${ready} of ${sources.length} videos ready`;
  $('#setup').hidden = status.credentials.transcription && status.credentials.answers;
  const missing = [];
  if (!status.credentials.transcription) missing.push('DEEPGRAM_API_KEY for transcription');
  if (!status.credentials.answers) missing.push('OPENAI_API_KEY for answers and translations');
  $('#setup-message').textContent = `Missing: ${missing.join('; ')}.`;
  if (status.links_error) {
    $('#ingest-note').textContent = status.links_error;
  } else if (status.job.running) {
    const done = status.job.items.filter((item) => ['ready', 'error'].includes(item.status)).length;
    $('#ingest-note').textContent = `${done} of ${status.job.items.length} processed. Keep the demo server running.`;
  } else if (status.job.items.length) {
    const failed = status.job.items.filter((item) => item.status === 'error').length;
    $('#ingest-note').textContent = failed ? `${failed} video${failed === 1 ? '' : 's'} need attention. You can retry processing.` : 'Your videos are ready to search.';
  } else {
    $('#ingest-note').textContent = 'Processing transcribes the full videos and may take several minutes.';
  }
  if (!ready) {
    $('#empty-state h2').textContent = 'Process your videos to begin';
    $('#empty-state p').textContent = 'Once your sources are ready, ask a question to get answers with original excerpts, English translations, and timestamped video links.';
  } else {
    $('#empty-state h2').textContent = 'Ask about your videos';
    $('#empty-state p').textContent = 'Find an explanation, compare ideas, or locate a specific moment. Each answer includes supporting excerpts and timestamped video links.';
  }
}

async function refreshStatus() {
  try {
    const status = await api('/api/status');
    if (JSON.stringify(currentStatus) !== JSON.stringify(status)) {
      currentStatus = status;
      if (status.backend === 'supermemory' && (videoOffset || videoFilter)) {
        const total = videoTotal(status);
        if (videoOffset >= total) videoOffset = Math.max(0, Math.floor((total - 1) / 50) * 50);
        const page = await api(`/api/videos?offset=${videoOffset}&status=${videoFilter}`);
        pageSources = page.sources;
      }
      showSources(status);
    }
    updateControls();
  } catch (error) {
    $('#collection-status').textContent = 'Server unavailable';
    $('#ingest-note').textContent = 'The demo server is not responding. Check the terminal and refresh this page.';
  }
}

function playExcerpt(source) {
  const url = new URL(source.url);
  const id = url.searchParams.get('v');
  if (!/^[A-Za-z0-9_-]{11}$/.test(id)) return;
  const frame = element('iframe');
  frame.src = `https://www.youtube-nocookie.com/embed/${id}?start=${Math.floor(source.start)}&end=${Math.ceil(source.end)}&autoplay=1`;
  frame.title = `${source.title} at ${source.time_range}`;
  frame.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
  frame.allowFullscreen = true;
  $('#player-title').textContent = `${source.title} · ${source.time_range}`;
  $('#external-player').href = source.url;
  $('#player-container').replaceChildren(frame);
  $('#player-dialog').showModal();
}

function evidenceNode(source, number, guide = null) {
  const article = element('section', 'evidence');
  const heading = element('div', 'evidence-heading');
  heading.append(element('span', 'evidence-title', number ? `${number}. ${source.title}` : source.title));
  const time = element('a', 'time-link', `${source.time_range} ↗`);
  time.href = source.url;
  time.target = '_blank';
  time.rel = 'noopener noreferrer';
  heading.append(time);
  article.append(heading);
  if (guide) article.append(element('p', 'excerpt-label', guide.match === 'direct' ? 'Relevant discussion' : 'Related discussion · partial match'));
  const summary = guide?.summary || source.summary;
  if (summary) {
    article.append(element('p', 'excerpt-label', guide ? 'What this moment covers' : 'Summary'), element('p', 'reference-summary', summary));
  }
  if (guide) {
    article.append(element('p', 'excerpt-label', 'Why it may help'), element('p', 'reference-summary', guide.why_relevant.replace(/^P\d+\b/, 'This moment').replace(/\bP\d+\b/g, 'another retrieved moment')));
    if (guide.limitation) article.append(element('p', 'excerpt-label', 'Limits of this excerpt'), element('p', 'reference-summary', guide.limitation));
  }
  const original = element('details', 'original-transcript');
  const toggle = element('summary', '', 'Show original excerpt');
  original.addEventListener('toggle', () => {
    toggle.textContent = original.open ? 'Hide original excerpt' : 'Show original excerpt';
  });
  original.append(toggle, element('blockquote', '', source.quote));
  article.append(original);
  if (source.english_translation) {
    const translation = element('div', 'translation');
    const unchanged = source.english_translation.trim() === source.quote.trim();
    translation.append(element('p', 'excerpt-label', unchanged ? 'English · original wording' : 'English translation · machine generated'));
    if (!unchanged) translation.append(element('p', '', source.english_translation));
    original.append(translation);
  } else if (source.translation_status === 'unavailable') {
    original.append(element('p', 'review-note', 'English translation is unavailable. Original wording is shown.'));
  }
  const actions = element('div', 'evidence-actions');
  const play = element('button', 'secondary', 'Play this excerpt');
  play.type = 'button';
  play.addEventListener('click', () => playExcerpt(source));
  const external = element('a', '', 'Open on YouTube ↗');
  external.href = source.url;
  external.target = '_blank';
  external.rel = 'noopener noreferrer';
  actions.append(play, external);
  article.append(actions);
  if (source.review_reasons?.length) article.append(element('p', 'review-note', `Listening check suggested: ${source.review_reasons.join(', ')}.`));
  return article;
}

function showAnswer(answer) {
  const output = $('#answer');
  output.replaceChildren();
  if (Array.isArray(answer.recommendations)) {
    if (answer.points?.length) {
      const reply = element('div', 'answer-reply');
      for (const point of answer.points) {
        const paragraph = element('p', 'reply-paragraph', point.text);
        const linked = new Set();
        for (const cite of point.citations) {
          const index = answer.recommendations.findIndex(r => r.citation.source_id === cite.source_id &&
            r.citation.start === cite.start && r.citation.end === cite.end);
          if (index < 0 || linked.has(index)) continue;
          linked.add(index);
          const link = element('a', 'reference-link', ` [${index + 1}]`);
          link.href = `#answer-reference-${index + 1}`;
          paragraph.append(link);
        }
        reply.append(paragraph);
      }
      output.append(reply);
    } else {
      output.append(element('p', 'answer-note', answer.message));
    }
    if (answer.recommendations.length) {
      const moments = element('section', 'answer-references');
      moments.append(element('h2', '', 'Suggested video moments'));
      for (const [index, guide] of answer.recommendations.entries()) {
        const node = evidenceNode(guide.citation, index + 1, guide);
        node.id = `answer-reference-${index + 1}`;
        moments.append(node);
      }
      output.append(moments);
      output.append(element('p', 'answer-warning', 'Descriptions summarize these excerpts. Open a moment to hear the discussion in context.'));
    }
    return;
  }
  if (!answer.points?.length) {
    output.append(element('p', 'answer-note', answer.message));
    return;
  }
  const reply = element('div', 'answer-reply');
  const references = [], referenceNumbers = new Map();
  for (const point of answer.points) {
    const paragraph = element('p', 'reply-paragraph', point.text);
    const cited = new Set();
    for (const source of point.citations) {
      const key = JSON.stringify([source.source_id || source.video_url || source.url, source.start, source.end, source.quote]);
      if (!referenceNumbers.has(key)) {
        references.push(source); referenceNumbers.set(key, references.length);
      }
      const number = referenceNumbers.get(key);
      if (cited.has(number)) continue;
      cited.add(number);
      const link = element('a', 'reference-link', ` [${number}]`);
      link.href = `#answer-reference-${number}`;
      paragraph.append(link);
    }
    reply.append(paragraph);
  }
  output.append(reply);
  const evidence = element('section', 'answer-references');
  evidence.append(element('h2', '', 'References'));
  for (const [index, source] of references.entries()) {
    const node = evidenceNode(source, index + 1);
    node.id = `answer-reference-${index + 1}`;
    evidence.append(node);
  }
  output.append(evidence);
  output.append(element('p', 'answer-warning', 'Summaries are paraphrases. Select Show original excerpt to read the captions, or open the linked video to check the wording.'));
  if (answer.translation_notice) output.append(element('p', 'answer-warning', answer.translation_notice));
}

$('#question-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (requesting) return;
  const question = $('#question').value.trim();
  if (!question) return;
  if (question.length > 6000) {
    requestMessage('Please shorten your question to under 6,000 characters.', true);
    return;
  }
  requesting = true;
  updateControls();
  $('#empty-state').hidden = true;
  $('#examples').hidden = true;
  $('#reset').hidden = false;
  $('#answer').replaceChildren();
  requestMessage('Finding relevant moments and preparing a reply from the excerpts…');
  const slow = setTimeout(() => requestMessage('Still checking which moments are useful for your question…'), 20000);
  try {
    const payload = {question};
    if ($('#video-scope').value) payload.source_id = $('#video-scope').value;
    const answer = await api('/api/ask', payload);
    showAnswer(answer);
    $('label[for="question"]').textContent = 'What would you like to know?';
    $('#question').value = question;
    $('#question').placeholder = 'Ask a question about the videos in your library.';
    if (answer.status === 'needs_clarification') $('#question').focus();
    requestMessage(answer.recording_error || (answer.record_id ? 'Response saved. Reopen or download it below in Saved responses.' : ''), Boolean(answer.recording_error));
  } catch (error) {
    requestMessage(error.message, true);
  } finally {
    clearTimeout(slow);
    requesting = false;
    updateControls();
    historyOffset = 0;
    await loadResponseHistory();
  }
});

$('#reset').addEventListener('click', () => {
  if (requesting) return;
  $('#question').value = '';
  $('#question').placeholder = 'Ask a question about the videos in your library.';
  $('label[for="question"]').textContent = 'What would you like to know?';
  $('#answer').replaceChildren();
  $('#empty-state').hidden = false;
  $('#examples').hidden = false;
  $('#reset').hidden = true;
  requestMessage('');
  updateControls();
  $('#question').focus();
});

document.querySelectorAll('[data-question]').forEach((button) => button.addEventListener('click', () => {
  if (requesting) return;
  $('#question').value = button.dataset.question;
  $('label[for="question"]').textContent = 'What would you like to know?';
  $('#question').focus();
  updateControls();
}));

$('#process').addEventListener('click', async () => {
  $('#process').disabled = true;
  try { await api('/api/ingest', {}); await refreshStatus(); }
  catch (error) { $('#ingest-note').textContent = error.message; updateControls(); }
});

$('#link-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('#add-link').disabled = true;
  try {
    await api('/api/ingest', {urls: [$('#podcast-url').value.trim()]});
    $('#podcast-url').value = '';
    await refreshStatus();
  } catch (error) { $('#ingest-note').textContent = error.message; updateControls(); }
});

$('#close-player').addEventListener('click', () => $('#player-dialog').close());
$('#player-dialog').addEventListener('close', () => $('#player-container').replaceChildren());

function videoTotal(status) {
  const c = status.counts;
  if (videoFilter === 'ready') return c.ready || 0;
  if (videoFilter === 'pending') return (c.queued || 0) + (c.processing || 0) + (c.indexing || 0);
  if (videoFilter === 'attention') return (c.error || 0) + (c.skipped || 0);
  return status.total;
}

function showChannelLibrary(status) {
  const counts = status.counts;
  $('#collection-status').textContent = status.read_only ? `${counts.ready || 0} video${counts.ready === 1 ? '' : 's'} indexed` : `${counts.ready || 0} of ${status.total} videos indexed`;
  $('#source-count').textContent = status.read_only ? status.library_title : `${status.channels.length} channels`;
  $('#setup').hidden = status.credentials.indexing && status.credentials.answers;
  $('#setup-message').textContent = [!status.credentials.indexing && 'Video indexing is not configured.', !status.credentials.answers && 'Answer generation is not configured.'].filter(Boolean).join(' ');
  const channels = document.createDocumentFragment();
  for (const channel of status.channels) {
    const row = element('article', 'channel-row');
    const title = element('a', 'channel-title', channel.title);
    title.href = channel.url; title.target = '_blank'; title.rel = 'noopener noreferrer';
    row.append(title);
    const c = channel.counts;
    const total = Object.values(c).reduce((a, b) => a + b, 0);
    const state = channel.paused ? 'Paused' : channel.state === 'scanning' || channel.state === 'queued' ? 'Discovering videos' : 'Channel saved';
    row.append(element('p', 'muted', `${state} · ${total} found · ${c.ready || 0} indexed`));
    const detail = [`${(c.queued || 0) + (c.processing || 0) + (c.indexing || 0)} pending`, `${(c.error || 0) + (c.skipped || 0)} need attention`];
    row.append(element('p', 'muted', detail.join(' · ')));
    if (channel.error) row.append(element('p', 'error', channel.error));
    const actions = element('div', 'channel-actions');
    for (const [action, label] of [[channel.paused ? 'resume' : 'pause', channel.paused ? 'Resume' : 'Pause'], ['sync', 'Check for new videos'], ['retry', 'Retry issues']]) {
      const button = element('button', 'text-button', label); button.type = 'button';
      button.disabled = action === 'retry' && !c.error && !c.skipped && channel.state !== 'error';
      button.addEventListener('click', async () => {
        button.disabled = true;
        try { await api('/api/channels/action', {channel_id: channel.id, action}); await refreshStatus(); }
        catch (error) { $('#channel-message').textContent = error.message; button.disabled = false; }
      });
      actions.append(button);
    }
    row.append(actions); channels.append(row);
  }
  $('#channel-list').replaceChildren(channels);
  $('#video-summary').textContent = `${counts.ready || 0} indexed · ${(counts.queued || 0) + (counts.processing || 0) + (counts.indexing || 0)} pending · ${(counts.error || 0) + (counts.skipped || 0)} need attention`;
  const sources = videoOffset || videoFilter ? pageSources : status.sources;
  const total = videoTotal(status);
  const list = document.createDocumentFragment();
  const labels = {queued: 'Queued', processing: 'Processing captions…', indexing: 'Indexing…', ready: 'Indexed', skipped: 'Needs a transcript', error: 'Needs attention'};
  for (const source of sources) {
    const row = element('article', 'source-item compact');
    const image = element('img', 'source-image'); image.src = `https://i.ytimg.com/vi/${source.id}/mqdefault.jpg`; image.alt = ''; image.loading = 'lazy';
    const detail = element('div');
    const link = element('a', '', source.title); link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    detail.append(link, element('p', `source-state ${source.state}`, source.error || labels[source.state] || source.state));
    row.append(image, detail); list.append(row);
  }
  if (!sources.length) list.append(element('p', 'muted', status.read_only ? 'No indexed Raj Shamani videos are available yet.' : status.total ? 'No videos match this status yet.' : 'Add a channel or video to start your library.'));
  $('#source-list').replaceChildren(list);
  $('#video-page-label').textContent = total ? `${videoOffset + 1}–${videoOffset + sources.length} of ${total}` : '0 videos';
  $('#video-pagination').hidden = total <= 50;
  $('#previous-videos').disabled = videoOffset === 0;
  $('#next-videos').disabled = videoOffset + sources.length >= total;
  const scope = $('#video-scope'), previous = scope.value;
  const choices = element('option', '', 'All indexed videos'); choices.value = '';
  const options = [choices];
  const catalog = [...new Map([...status.sources, ...sources].filter(s => s.state === 'ready').map(s => [s.id, s])).values()];
  for (const source of catalog) { const option = element('option', '', source.title); option.value = source.id; options.push(option); }
  // Do not change a user's selection while their question is being prepared.
  if (!requesting) { scope.replaceChildren(...options); scope.value = catalog.some(s => s.id === previous) ? previous : ''; }
  $('#ingest-note').textContent = !status.worker_running ? 'The import worker is stopped. Restart the app to resume.' : 'Imports resume after a restart. Already indexed videos are kept.';
  if (status.read_only) {
    $('#empty-state h2').textContent = counts.ready ? 'Find a useful place to start' : 'The video library is not ready yet';
    $('#empty-state p').textContent = counts.ready ? 'Get a clear reply from the relevant passages, then explore the supporting moments and their limitations.' : 'Questions will be available once the library has indexed videos.';
  }
}

$('#channel-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (findingChannel) return;
  findingChannel = true; channelPreview = null;
  $('#channel-preview').hidden = true;
  $('#channel-message').textContent = 'Looking up this channel…'; updateControls();
  try {
    channelPreview = await api('/api/channels/preview', {channel: $('#channel-handle').value.trim()});
    const preview = $('#channel-preview');
    const title = element('a', 'channel-title', channelPreview.title);
    title.href = channelPreview.url; title.target = '_blank'; title.rel = 'noopener noreferrer';
    const recent = element('ul', 'channel-sample');
    for (const video of channelPreview.sample) recent.append(element('li', '', video.title));
    const button = element('button', 'primary', 'Import long-form videos'); button.type = 'button';
    button.disabled = !currentStatus?.credentials.indexing;
    const selectedChannel = channelPreview;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await api('/api/channels', {channel_id: selectedChannel.id});
        preview.hidden = true;
        $('#channel-message').textContent = `${selectedChannel.title} added. Discovering and indexing videos in the background.`;
        await refreshStatus();
      } catch (error) { $('#channel-message').textContent = error.message; button.disabled = false; }
    });
    preview.replaceChildren(title, element('p', 'muted', 'Recent videos — preview only'), recent,
      element('p', 'muted', 'No video-count limit is currently set. Import discovers the Videos tab; the indexed count updates in Your videos.'),
      element('p', 'muted', 'Only long-form uploads are imported. Shorts are excluded. Large channels take time; you can pause at any time. Videos without usable captions need attention.'), button);
    preview.hidden = false; $('#channel-message').textContent = '';
  } catch (error) { $('#channel-message').textContent = error.message; }
  finally { findingChannel = false; updateControls(); }
});

async function videoPage(direction) {
  const next = Math.max(0, videoOffset + direction * 50);
  try {
    const page = await api(`/api/videos?offset=${next}&status=${videoFilter}`);
    videoOffset = next; pageSources = page.sources; showSources(currentStatus);
  } catch (error) { $('#ingest-note').textContent = error.message; }
}
$('#previous-videos').addEventListener('click', () => videoPage(-1));
$('#next-videos').addEventListener('click', () => videoPage(1));
$('#video-filter').addEventListener('change', async () => {
  const selected = $('#video-filter').value;
  try {
    const page = await api(`/api/videos?offset=0&status=${selected}`);
    videoFilter = selected; videoOffset = 0; pageSources = page.sources;
    showSources(currentStatus);
  } catch (error) {
    $('#video-filter').value = videoFilter;
    $('#ingest-note').textContent = error.message;
  }
});
async function loadResponseHistory() {
  try {
    const history = await api(`/api/responses?offset=${historyOffset}`);
    $('#history-count').textContent = `(${history.total})`;
    $('#history-message').textContent = history.total ? '' : 'No responses recorded yet. Your next question will be saved here.';
    const list = document.createDocumentFragment();
    const labels = {recommendations: 'Suggested moments', answered: 'Answered', error: 'Request failed', insufficient_evidence: 'No useful match', invalid_evidence: 'Evidence check failed', needs_clarification: 'Needs clarification'};
    for (const item of history.items) {
      const row = element('article', 'saved-response');
      row.append(element('p', '', item.question || 'Empty question'));
      row.append(element('p', 'muted', `${new Date(item.created_at).toLocaleString()} · ${labels[item.status] || item.status}`));
      const actions = element('div', 'saved-response-actions');
      const view = element('button', 'text-button', 'View response'); view.type = 'button';
      view.addEventListener('click', async () => {
        if (requesting) return;
        try {
          const record = await api(`/api/responses/${item.id}`);
          // Opening a recording makes no generation or ingestion request.
          if (requesting) return;
          $('#question').value = record.question;
          const scope = $('#video-scope');
          if (record.source_id && !Array.from(scope.options || []).some(option => option.value === record.source_id)) {
            const option = element('option', '', `Saved video: ${record.source_id}`);
            option.value = record.source_id; scope.append(option);
          }
          scope.value = record.source_id || '';
          $('label[for="question"]').textContent = 'What would you like to know?';
          $('#empty-state').hidden = true; $('#examples').hidden = true; $('#reset').hidden = false;
          $('#answer').replaceChildren();
          if (record.response.error) requestMessage(record.response.error, true);
          else {
            showAnswer(record.response);
            requestMessage(`Saved response · ${new Date(record.created_at).toLocaleString()} · ${record.model} · ${record.elapsed_seconds}s`);
          }
          updateControls();
          $('#question').focus();
        } catch (error) { $('#history-message').textContent = error.message; }
      });
      const download = element('a', '', 'Download JSON');
      download.href = `/api/responses/${item.id}`; download.download = `response-${item.id}.json`;
      actions.append(view, download); row.append(actions); list.append(row);
    }
    $('#history-list').replaceChildren(list);
    $('#history-pagination').hidden = history.total <= 20;
    $('#history-newer').disabled = historyOffset === 0;
    $('#history-older').disabled = historyOffset + history.items.length >= history.total;
  } catch (error) { $('#history-message').textContent = 'Saved responses could not be loaded. Refresh to try again.'; }
}
$('#history-newer').addEventListener('click', () => { historyOffset = Math.max(0, historyOffset - 20); return loadResponseHistory(); });
$('#history-older').addEventListener('click', () => { historyOffset += 20; return loadResponseHistory(); });
refreshStatus();
loadResponseHistory();
setInterval(refreshStatus, 3000);
