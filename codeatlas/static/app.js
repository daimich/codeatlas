const $ = (id) => document.getElementById(id);
const node = (tag, text, cls) => { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; };
async function api(path, body) {
  const response = await fetch('/api/' + path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data;
}
function status(message) { $('status').textContent = message; }
function codeCard(hit, distance) {
  const card = node('article', '', 'card'); const header = node('div', '', 'card-header');
  header.append(node('strong', hit.qualified), node('span', hit.kind, 'badge'));
  card.append(header, node('div', hit.path + ':' + hit.start + '–' + hit.end + (distance ? ' · caller distance ' + distance : ''), 'citation'));
  const pre = node('pre', ''); pre.append(node('code', hit.text)); card.append(pre);
  if (['function', 'class'].includes(hit.kind)) {
    const button = node('button', 'Trace callers →', 'trace');
    button.addEventListener('click', () => trace(hit.id)); card.append(button);
  }
  return card;
}
async function trace(symbol) {
  status('Walking the call graph…');
  try {
    const result = await api('impact', {symbol, depth: 3}); $('results').replaceChildren();
    $('mode').textContent = 'Impact of ' + result.symbol.qualified;
    $('results').append(node('p', result.note, 'muted'));
    if (!result.affected.length) $('results').append(node('div', 'No callers were resolved in this snapshot.', 'empty'));
    result.affected.forEach(hit => $('results').append(codeCard(hit, hit.distance)));
    status(result.affected.length + ' reachable callers · maximum depth 3');
  } catch (error) { status(error.message); }
}
$('query-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('submit').disabled = true; status('Searching the repository…');
  try {
    const explain = $('answer-mode').value === 'ask';
    const result = await api(explain ? 'ask' : 'search', {question: $('query').value, k: explain ? 4 : 8}); $('results').replaceChildren();
    if (explain) {
      const showEvidence = result.abstained && result.evidence.length > 0;
      $('mode').textContent = showEvidence ? 'Source evidence · model abstained' : (result.mode === 'ollama' ? 'Explanation with sources' : 'Source evidence');
      if (result.abstained) $('results').append(node('div', showEvidence ? 'The model could not support an answer. Review the retrieved source below.' : 'No supporting evidence was found.', 'empty'));
      for (const claim of result.claims) {
        const card = node('article', '', 'card');
        card.append(node('p', claim.text), node('div', claim.path + ':' + claim.start + '–' + claim.end, 'citation'));
        const pre = node('pre', ''); pre.append(node('code', claim.quote)); card.append(pre); $('results').append(card);
      }
      if (result.mode === 'evidence' || showEvidence) result.evidence.forEach(hit => $('results').append(codeCard(hit)));
      status(result.retrieval + ' · total ' + result.total_ms + ' ms'); return;
    }
    $('mode').textContent = result.hits.length + ' search results';
    if (!result.hits.length) $('results').append(node('div', 'No matching code found. Try a symbol name or a phrase from a docstring.', 'empty'));
    result.hits.forEach(hit => $('results').append(codeCard(hit)));
    status(result.retrieval + ' · ' + result.latency_ms + ' ms');
  } catch (error) { status(error.message); }
  finally { $('submit').disabled = false; }
});
document.querySelectorAll('[data-query]').forEach(button => button.addEventListener('click', () => {
  $('query').value = button.dataset.query; $('query').focus();
}));
async function refresh() {
  const meta = await api('status');
  $('inventory').replaceChildren(); $('count').textContent = meta.files + ' files indexed';
  [['Source files', meta.files], ['Searchable records', meta.records], ['Resolved calls', meta.edges]].forEach(([label, value]) => {
    const row = node('div', '', 'metric'); row.append(node('span', label), node('strong', String(value))); $('inventory').append(row);
  });
  $('inventory').append(node('p', 'Python: AST symbols and call edges. Other languages: source text search.', 'muted'));
  if (!meta.files) $('inventory').append(node('p', 'Run python -m codeatlas index /path/to/repository to add source files.', 'muted'));
  $('reindex').disabled = !meta.can_reindex;
  $('model-info').textContent = meta.retrieval + ' · ' + (meta.ollama_model || 'source evidence');
  status(meta.warnings.length ? meta.warnings.length + ' indexing warnings · see CLI status' : 'Snapshot ready.');
}
$('reindex').addEventListener('click', async () => {
  $('reindex').disabled = true; status('Refreshing the repository…');
  try { const result = await api('reindex', {}); $('results').replaceChildren(); await refresh(); status(result.changed_files + ' changed · ' + result.unchanged_files + ' unchanged · ' + result.deleted_files + ' removed'); }
  catch(error) { status(error.message); }
  finally { $('reindex').disabled = false; }
});
refresh().catch(error => status(error.message));
