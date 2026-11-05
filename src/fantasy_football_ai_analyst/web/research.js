/* Evidence presentation only. Retrieval, scoring, and player matching live in Python. */
export function setupResearch({ request, escape, onChange }) {
  const $ = (selector) => document.querySelector(selector);
  let activeRequest = null;
  let requestId = 0;
  const dates = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' });
  $('#research-query').value = new URLSearchParams(location.search).get('question') || '';

  function displayDate(value) {
    return value ? dates.format(new Date(value)) : 'Not recorded';
  }

  function highlight(text, words) {
    // Escape the source before adding our own markup, including literal HTML in notes.
    const safeWords = words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (!safeWords.length) return escape(text);
    const pattern = new RegExp(`(${safeWords.join('|')})`, 'giu');
    return String(text).split(pattern).map((part, index) => (
      index % 2 ? `<mark>${escape(part)}</mark>` : escape(part)
    )).join('');
  }

  function card(result, index) {
    const isNews = result.source_type === 'fpl_news';
    const timestamp = isNews ? result.news_added : result.published_at;
    const old = isNews && timestamp && Date.now() - new Date(timestamp).getTime() > 14 * 86400000;
    const future = timestamp && new Date(timestamp).getTime() > Date.now();
    const tag = isNews ? 'FPL NEWS NOTE' : result.source_name === 'Touchline methodology' ? 'METHODOLOGY' : 'CURATED NOTE';
    const dateLabel = isNews ? 'News added' : 'Published';
    const sourceUrl = result.source_url && /^https?:\/\//i.test(result.source_url) ? result.source_url : null;
    return `<article class="evidence-card" aria-labelledby="evidence-title-${index}">
      <div class="evidence-top"><span class="evidence-reference">[${index + 1}]</span><span class="evidence-type">${tag}</span><span class="evidence-date ${old || future || !timestamp ? 'uncertain' : ''}">${dateLabel} ${escape(displayDate(timestamp))}${old ? ' · Over 14 days old' : ''}${future ? ' · Future-dated' : ''}</span></div>
      <h3 id="evidence-title-${index}">${escape(result.title)}</h3>
      <p class="evidence-text">${highlight(result.text, result.matched_words)}</p>
      <div class="evidence-matches"><span>MATCHED WORDS</span>${result.matched_words.map((word) => `<span class="evidence-word">${escape(word)}</span>`).join('')}<span class="evidence-score" title="Weighted keyword overlap, not a confidence or probability">Ranking score ${result.score}</span></div>
      <div class="evidence-source"><span>${escape(result.source_name)}</span>${sourceUrl ? `<a href="${escape(sourceUrl)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : '<span>Local reference</span>'}</div>
      <details class="evidence-details"><summary>Source details</summary><dl><div><dt>Source record</dt><dd>${escape(result.source_document_id)}</dd></div><div><dt>Saved file / reference</dt><dd>${escape(result.source_file || 'Not recorded')}</dd></div><div><dt>Publication date</dt><dd>${escape(displayDate(result.published_at))}</dd></div><div><dt>Retrieval date</dt><dd>${escape(displayDate(result.retrieved_at))}</dd></div></dl>${isNews ? '<p>The linked FPL endpoint changes over time. This passage comes from your saved snapshot; the news-added date is not an article publication date.</p>' : ''}</details>
    </article>`;
  }

  function showState(title, message, loading = false) {
    $('#research-state').hidden = false;
    $('#research-state').innerHTML = `${loading ? '<div class="loading-spinner"></div>' : '<div class="research-state-mark" aria-hidden="true">?</div>'}<h3>${escape(title)}</h3><p>${escape(message)}</p>`;
  }

  async function search(question = $('#research-query').value) {
    const query = question.trim();
    $('#research-query').value = query;
    activeRequest?.abort();
    const id = ++requestId;
    if (!query) {
      $('#research-results').replaceChildren();
      $('#research-warnings').hidden = true;
      $('#research-focus').hidden = true;
      $('#research-results').setAttribute('aria-busy', 'false');
      $('#research-submit').disabled = false;
      $('#research-result-summary').textContent = 'Enter a question to get started.';
      showState('Start with a player or a topic.', 'For example: “Any updates on Saka?” or “Why use a minutes filter?”');
      onChange();
      return;
    }
    const controller = new AbortController();
    activeRequest = controller;
    const timeout = setTimeout(() => controller.abort(), 15000);
    $('#research-results').replaceChildren();
    $('#research-results').setAttribute('aria-busy', 'true');
    $('#research-submit').disabled = true;
    $('#research-focus').hidden = true;
    $('#research-warnings').hidden = true;
    $('#research-result-summary').textContent = 'Looking through your saved sources…';
    showState('Following the evidence.', 'Searching saved notes and retaining their original source information.', true);
    onChange();
    try {
      const params = new URLSearchParams({ query, limit: $('#research-limit').value });
      const result = await request(`/knowledge/search?${params}`, controller.signal);
      if (id !== requestId) return;
      $('#research-result-summary').textContent = `${result.count} ${result.count === 1 ? 'passage' : 'passages'} found · ${result.document_count} saved passages searched`;
      $('#research-focus').hidden = result.matched_players.length === 0;
      $('#research-focus').textContent = `Matched player names: ${result.matched_players.join(', ')}`;
      $('#research-warnings').hidden = false;
      $('#research-warnings').innerHTML = result.warnings.map((warning) => `<p>${escape(warning)}</p>`).join('');
      if (!result.results.length) {
        showState('Not enough evidence. That matters, too.', 'No supporting saved passage was found. A missing note does not mean a player is fit. Try a full player name, different wording, or add a sourced note.');
        return;
      }
      $('#research-state').hidden = true;
      $('#research-results').innerHTML = result.results.map(card).join('');
    } catch (error) {
      if (id !== requestId) return;
      $('#research-result-summary').textContent = 'Search unavailable';
      showState('A pause in the research.', error.name === 'AbortError'
        ? 'The search took too long. Please try again.'
        : error.message || 'The saved sources could not be reached. Please try again.');
    } finally {
      clearTimeout(timeout);
      if (id === requestId) {
        $('#research-results').setAttribute('aria-busy', 'false');
        $('#research-submit').disabled = false;
      }
    }
  }

  $('#research-form').addEventListener('submit', (event) => { event.preventDefault(); search(); });
  $('#research-limit').addEventListener('change', () => { if ($('#research-query').value.trim()) search(); });
  document.querySelectorAll('[data-research-question]').forEach((button) => button.addEventListener('click', () => search(button.dataset.researchQuestion)));
  return { search };
}
