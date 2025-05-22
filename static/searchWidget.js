// static/js/searchWidget.js
// A reusable search + suggestions widget

/**
 * Initialize a search box with suggestion dropdown, debounced input,
 * arrow-key navigation, and Enter-to-select.
 *
 * @param {{
 *   inputSelector: string,      // CSS selector for the <input>
 *   listSelector: string,       // CSS selector for the <ul> suggestions list
 *   onSuggest: (raw: Array<{ display: string, key: string }>) => Array<{ display: string, key: string }>,
 *   onSelect: (rawKey: string) => void,
 *   minChars?: number,
 *   debounceMs?: number
 * }} opts
 */
export function initSearch(opts) {
  const {
    inputSelector,
    listSelector,
    onSuggest,
    onSelect,
    minChars = 2,
    debounceMs = 250,
  } = opts;

  const inputEl = document.querySelector(inputSelector);
  const listEl  = document.querySelector(listSelector);
  let suggestionKeys = [];
  let selectedIndex = -1;

  // Debounce helper
  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  // Render suggestions into the dropdown
  function renderList(items) {
    listEl.innerHTML = items
      .map((item, idx) => `
        <li data-idx="${idx}" class="suggestion-item">
          ${item.display}
        </li>
      `)
      .join('');
    listEl.style.display = items.length ? 'block' : 'none';
    suggestionKeys = items.map(i => i.key);
    selectedIndex = 0;
    highlight();
  }

  function highlight() {
    Array.from(listEl.children).forEach((li, i) => {
      li.classList.toggle('highlighted', i === selectedIndex);
    });
  }

  // Fetch raw suggestions from server
  async function fetchRaw(q) {
    const res = await fetch(`/api/pokemon/suggestions?query=${encodeURIComponent(q)}`);
    const blob = await res.json();
    return blob.suggestions || [];
  }

  // Handle input events
  const handleInput = debounce(async (e) => {
    const q = e.target.value.trim().toLowerCase();
    if (q.length < minChars) {
      listEl.style.display = 'none';
      return;
    }
    const raw = await fetchRaw(q);
    const collapsed = onSuggest(raw);
    renderList(collapsed);
  }, debounceMs);

  // Keyboard navigation
  function handleKey(e) {
    const items = Array.from(listEl.children);
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      selectedIndex = Math.min(items.length - 1, selectedIndex + 1);
      highlight();
      e.preventDefault();
    } else if (e.key === 'ArrowUp') {
      selectedIndex = Math.max(0, selectedIndex - 1);
      highlight();
      e.preventDefault();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const key = suggestionKeys[selectedIndex];
      onSelect(key);
    }
  }

  // Mouse click on suggestions
  listEl.addEventListener('click', (e) => {
    const li = e.target.closest('li[data-idx]');
    if (!li) return;
    const idx = parseInt(li.dataset.idx, 10);
    const key = suggestionKeys[idx];
    onSelect(key);
  });

  // Wire up events
  inputEl.addEventListener('input', handleInput);
  inputEl.addEventListener('keydown', handleKey);
}
