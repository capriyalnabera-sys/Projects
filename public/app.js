// State
let currentTab = 'news';
let currentPage = 1;
let newsPage = 1;
let roundsPage = 1;
let currentSort = { by: 'date_added', order: 'DESC' };
let filters = { q: '', sector: '', stage: '', geography: '', source: '', is_new: '' };
let selectedCountry = '';
let debounceTimer = null;

// DOM Elements
const $ = (id) => document.getElementById(id);
const searchInput = $('searchInput');
const filterSector = $('filterSector');
const filterStage = $('filterStage');
const filterGeography = $('filterGeography');
const filterSource = $('filterSource');
const investorTableBody = $('investorTableBody');
const pagination = $('pagination');
const toast = $('toast');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadFilters();
  loadFundingNews();
  setupEventListeners();
});

function setupEventListeners() {
  // Country toggle
  document.querySelectorAll('.country-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.country-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      selectedCountry = btn.dataset.country;
      // Reload current tab data
      if (currentTab === 'news') { newsPage = 1; loadFundingNews(); }
      else if (currentTab === 'rounds') { roundsPage = 1; loadFundingRounds(); }
      else if (currentTab === 'all' || currentTab === 'new') { currentPage = 1; loadInvestors(); }
    });
  });

  // Investor search with debounce
  searchInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      filters.q = searchInput.value;
      currentPage = 1;
      loadInvestors();
    }, 300);
  });

  // News search with debounce
  const newsSearchInput = $('newsSearchInput');
  if (newsSearchInput) {
    newsSearchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        newsPage = 1;
        loadFundingNews();
      }, 300);
    });
  }

  // News source filter
  const newsSourceFilter = $('newsSourceFilter');
  if (newsSourceFilter) {
    newsSourceFilter.addEventListener('change', () => {
      newsPage = 1;
      loadFundingNews();
    });
  }

  // Filters
  filterSector.addEventListener('change', () => { filters.sector = filterSector.value; currentPage = 1; loadInvestors(); });
  filterStage.addEventListener('change', () => { filters.stage = filterStage.value; currentPage = 1; loadInvestors(); });
  filterGeography.addEventListener('change', () => { filters.geography = filterGeography.value; currentPage = 1; loadInvestors(); });
  if (filterSource) {
    filterSource.addEventListener('change', () => { filters.source = filterSource.value; currentPage = 1; loadInvestors(); });
  }

  // Clear filters
  $('btnClearFilters').addEventListener('click', () => {
    searchInput.value = '';
    filterSector.value = '';
    filterStage.value = '';
    filterGeography.value = '';
    if (filterSource) filterSource.value = '';
    filters = { q: '', sector: '', stage: '', geography: '', source: '', is_new: '' };
    currentPage = 1;
    loadInvestors();
  });

  // Tabs
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentTab = tab.dataset.tab;

      // Hide all tab sections
      ['tabAll', 'tabNews', 'tabRounds', 'tabLogs', 'investorFiltersSection'].forEach(id => {
        const el = $(id);
        if (el) el.classList.add('hidden');
      });

      if (currentTab === 'news') {
        $('tabNews').classList.remove('hidden');
        loadFundingNews();
      } else if (currentTab === 'rounds') {
        $('tabRounds').classList.remove('hidden');
        loadFundingRounds();
      } else if (currentTab === 'all') {
        $('investorFiltersSection').classList.remove('hidden');
        $('tabAll').classList.remove('hidden');
        filters.is_new = '';
        currentPage = 1;
        loadInvestors();
      } else if (currentTab === 'new') {
        $('investorFiltersSection').classList.remove('hidden');
        $('tabAll').classList.remove('hidden');
        filters.is_new = '1';
        currentPage = 1;
        loadInvestors();
      } else if (currentTab === 'logs') {
        $('tabLogs').classList.remove('hidden');
        loadScrapeLogs();
      }
    });
  });

  // Sortable columns
  document.querySelectorAll('.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const sortBy = th.dataset.sort;
      if (currentSort.by === sortBy) {
        currentSort.order = currentSort.order === 'ASC' ? 'DESC' : 'ASC';
      } else {
        currentSort.by = sortBy;
        currentSort.order = 'ASC';
      }
      document.querySelectorAll('.sortable').forEach(s => s.classList.remove('asc', 'desc'));
      th.classList.add(currentSort.order === 'ASC' ? 'asc' : 'desc');
      loadInvestors();
    });
  });

  // Scrape dropdown items
  const scrapeMenu = $('scrapeMenu');
  if (scrapeMenu) {
    scrapeMenu.querySelectorAll('a[data-source]').forEach(link => {
      link.addEventListener('click', async (e) => {
        e.preventDefault();
        await triggerScrape(link.dataset.source);
      });
    });
  }

  // Seed Data button
  const btnSeedData = $('btnSeedData');
  if (btnSeedData) {
    btnSeedData.addEventListener('click', async () => {
      btnSeedData.disabled = true;
      btnSeedData.textContent = 'Seeding...';
      try {
        const res = await fetch('/api/seed', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast('Investor data seeded successfully!', 'success');
          loadInvestors();
          loadStats();
          loadFilters();
        } else {
          showToast('Seed failed: ' + (data.error || 'Unknown error'), 'error');
        }
      } catch (err) {
        showToast('Seed failed: ' + err.message, 'error');
      }
      btnSeedData.disabled = false;
      btnSeedData.textContent = 'Seed Data';
    });
  }

  // Add investor button
  $('btnAddInvestor').addEventListener('click', () => openModal());
  $('modalClose').addEventListener('click', closeModal);
  $('btnCancelForm').addEventListener('click', closeModal);
  $('investorModal').addEventListener('click', (e) => {
    if (e.target === $('investorModal')) closeModal();
  });
  $('investorForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    await saveInvestor();
  });

  // Close dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.dropdown')) {
      document.querySelectorAll('.dropdown.open').forEach(d => d.classList.remove('open'));
    }
  });
}

// ─── Scrape ───
async function triggerScrape(source) {
  const btn = $('btnScrape');
  const originalHTML = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="display:inline-block;width:12px;height:12px;border:2px solid white;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;margin-right:6px;vertical-align:middle;"></span> Scraping...';

  try {
    const url = source === 'all' ? '/api/scrape/all' : '/api/scrape';
    const body = source === 'all' ? { maxPages: 2 } : { source, maxPages: 2 };
    await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    showToast(`Scraper started for ${source === 'all' ? 'all sources' : source}. Results will appear shortly.`, 'success');
    pollScrapeStatus(btn, originalHTML);
  } catch (err) {
    showToast('Failed to start scraper: ' + err.message, 'error');
    btn.disabled = false;
    btn.innerHTML = originalHTML;
  }
}

// ─── API Calls ───
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    const stats = await res.json();
    $('statTotal').textContent = stats.total.toLocaleString();
    $('statNewToday').textContent = stats.newToday.toLocaleString();
    const statNews = $('statNews');
    if (statNews) statNews.textContent = (stats.newsCount || 0).toLocaleString();
    const statLastScrape = $('statLastScrape');
    if (statLastScrape) {
      if (stats.lastScrape) {
        statLastScrape.textContent = formatRelativeTime(new Date(stats.lastScrape.started_at));
      } else {
        statLastScrape.textContent = 'Never';
      }
    }
    const statRounds = $('statRounds');
    if (statRounds) statRounds.textContent = (stats.roundsCount || 0).toLocaleString();
  } catch (err) {
    console.error('Error loading stats:', err);
  }
}

async function loadFilters() {
  try {
    const res = await fetch('/api/filters');
    const options = await res.json();
    populateSelect(filterSector, options.sectors, 'All Sectors');
    populateSelect(filterStage, options.stages, 'All Stages');
    populateSelect(filterGeography, options.geographies, 'All Geographies');
    if (filterSource && options.sources) {
      populateSelect(filterSource, options.sources, 'All Sources');
    }
  } catch (err) {
    console.error('Error loading filters:', err);
  }
}

function populateSelect(select, items, defaultLabel) {
  if (!select) return;
  select.innerHTML = `<option value="">${defaultLabel}</option>`;
  items.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item;
    opt.textContent = item;
    select.appendChild(opt);
  });
}

async function loadInvestors() {
  try {
    const params = new URLSearchParams({ page: currentPage, limit: 50, sort_by: currentSort.by, sort_order: currentSort.order });
    if (filters.q) params.set('q', filters.q);
    if (filters.sector) params.set('sector', filters.sector);
    if (filters.stage) params.set('stage', filters.stage);
    if (filters.geography) params.set('geography', filters.geography);
    if (filters.source) params.set('source', filters.source);
    if (filters.is_new) params.set('is_new', filters.is_new);
    if (selectedCountry) params.set('geography', selectedCountry);

    const res = await fetch(`/api/investors?${params}`);
    const data = await res.json();
    renderInvestors(data.investors);
    renderPagination(data, 'pagination', goToPage);
  } catch (err) {
    investorTableBody.innerHTML = `<tr><td colspan="13" class="empty-state">Error loading data: ${err.message}</td></tr>`;
  }
}

function renderInvestors(investors) {
  if (investors.length === 0) {
    investorTableBody.innerHTML = `<tr><td colspan="13" class="empty-state">No investors found. Try adjusting your filters or run the scraper.</td></tr>`;
    return;
  }
  investorTableBody.innerHTML = investors.map(inv => `
    <tr class="${inv.is_new ? 'new-row' : ''}">
      <td title="${esc(inv.name)}">
        ${esc(inv.name)}
        ${inv.is_new ? '<span class="tag new">NEW</span>' : ''}
      </td>
      <td title="${esc(inv.institution || '')}">${esc(inv.institution || '-')}</td>
      <td title="${esc(inv.title || '')}">${esc(inv.title || '-')}</td>
      <td>${esc(inv.avg_cheque_size || '-')}</td>
      <td title="${esc(inv.geographies || '')}">
        ${inv.geographies ? inv.geographies.split(',').slice(0, 2).map(g => `<span class="tag">${esc(g.trim())}</span>`).join('') : '-'}
      </td>
      <td title="${esc(inv.sectors || '')}">
        ${inv.sectors ? inv.sectors.split(',').slice(0, 3).map(s => `<span class="tag">${esc(s.trim())}</span>`).join('') : '-'}
      </td>
      <td>${inv.stage ? `<span class="tag stage">${esc(inv.stage)}</span>` : '-'}</td>
      <td>${esc(inv.shareholding || '-')}</td>
      <td>${inv.email ? `<a href="mailto:${esc(inv.email)}">${esc(inv.email)}</a>` : '-'}</td>
      <td>${inv.website ? `<a href="${esc(inv.website)}" target="_blank" rel="noopener">Link</a>` : '-'}</td>
      <td>${inv.source ? `<span class="source-badge ${esc(inv.source)}">${esc(inv.source)}</span>` : '-'}</td>
      <td>${formatDate(inv.date_added)}</td>
      <td class="actions-cell">
        <button class="edit-btn" onclick="editInvestor(${inv.id})" title="Edit">Edit</button>
        <button class="delete-btn" onclick="removeInvestor(${inv.id})" title="Delete">Del</button>
      </td>
    </tr>
  `).join('');
}

// ─── Funding News ───
async function loadFundingNews() {
  const newsGrid = $('newsGrid');
  if (!newsGrid) return;

  try {
    const params = new URLSearchParams({ page: newsPage, limit: 30 });
    const newsSearchInput = $('newsSearchInput');
    if (newsSearchInput && newsSearchInput.value) params.set('q', newsSearchInput.value);
    const newsSourceFilter = $('newsSourceFilter');
    if (newsSourceFilter && newsSourceFilter.value) params.set('source', newsSourceFilter.value);
    if (selectedCountry) params.set('country', selectedCountry);

    const res = await fetch(`/api/funding-news?${params}`);
    const data = await res.json();

    if (data.news.length === 0) {
      newsGrid.innerHTML = '<div class="empty-state">No funding news yet. Run the scraper to fetch the latest news from India & Singapore.</div>';
      const np = $('newsPagination');
      if (np) np.innerHTML = '';
      return;
    }

    newsGrid.innerHTML = data.news.map(n => `
      <div class="news-card">
        <div class="news-card-header">
          <div class="news-card-title">
            ${n.source_url ? `<a href="${esc(n.source_url)}" target="_blank" rel="noopener">${esc(n.headline)}</a>` : esc(n.headline)}
          </div>
        </div>
        <div class="news-card-meta">
          ${n.source ? `<span class="source-badge ${esc(n.source)}">${esc(n.source)}</span>` : ''}
          ${n.country ? `<span class="country-badge ${esc(n.country.toLowerCase())}">${n.country === 'India' ? '&#127470;&#127475;' : n.country === 'Singapore' ? '&#127480;&#127468;' : ''} ${esc(n.country)}</span>` : ''}
          <span class="meta-item">${formatDate(n.published_date || n.date_added)}</span>
        </div>
        <div class="news-card-key-details">
          ${n.amount ? `<div class="key-detail"><span class="key-label">Raised</span><span class="key-value amount">${esc(n.amount)}</span></div>` : ''}
          ${n.valuation ? `<div class="key-detail"><span class="key-label">Valuation</span><span class="key-value valuation">${esc(n.valuation)}</span></div>` : ''}
          ${n.valuation_multiple ? `<div class="key-detail"><span class="key-label">Multiple</span><span class="key-value multiple">${esc(n.valuation_multiple)}</span></div>` : ''}
        </div>
        ${n.summary ? `<div class="news-card-summary">${esc(n.summary)}</div>` : ''}
        <div class="news-card-tags">
          ${n.startup_name ? `<span class="tag startup">${esc(n.startup_name)}</span>` : ''}
          ${n.round_type ? `<span class="tag stage">${esc(n.round_type)}</span>` : ''}
          ${n.sector ? n.sector.split(',').slice(0, 3).map(s => `<span class="tag">${esc(s.trim())}</span>`).join('') : ''}
        </div>
        ${n.investors ? `<div class="news-card-investors"><span class="investors-label">Investors:</span> ${n.investors.split(',').slice(0, 5).map(i => `<span class="investor-chip">${esc(i.trim())}</span>`).join('')}${n.investors.split(',').length > 5 ? `<span class="investor-chip more">+${n.investors.split(',').length - 5} more</span>` : ''}</div>` : ''}
      </div>
    `).join('');

    const np = $('newsPagination');
    if (np) renderPagination(data, 'newsPagination', goToNewsPage);
  } catch (err) {
    newsGrid.innerHTML = `<div class="empty-state">Error loading funding news: ${err.message}</div>`;
  }
}

// ─── Funding Rounds (Deal Tracker) ───
async function loadFundingRounds() {
  try {
    const params = new URLSearchParams({ page: roundsPage, limit: 50 });
    if (selectedCountry) params.set('country', selectedCountry);

    const res = await fetch(`/api/funding-rounds?${params}`);
    const data = await res.json();
    const tbody = $('roundsTableBody');

    if (data.rounds.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty-state">No funding rounds recorded yet. Run the scraper to fetch data from India & Singapore.</td></tr>`;
      return;
    }

    tbody.innerHTML = data.rounds.map(r => `
      <tr>
        <td><strong>${esc(r.startup_name || '-')}</strong></td>
        <td>${r.country ? `<span class="country-badge ${esc((r.country || '').toLowerCase())}">${esc(r.country)}</span>` : '-'}</td>
        <td class="amount-cell"><strong>${esc(r.amount || '-')}</strong></td>
        <td>${r.round_type ? `<span class="tag stage">${esc(r.round_type)}</span>` : '-'}</td>
        <td class="valuation-cell">${r.valuation ? `<strong>${esc(r.valuation)}</strong>` : '-'}</td>
        <td class="multiple-cell">${r.valuation_multiple ? `<span class="multiple-badge">${esc(r.valuation_multiple)}</span>` : '-'}</td>
        <td title="${esc(r.investors || '')}">${esc((r.investors || '').substring(0, 80))}${(r.investors || '').length > 80 ? '...' : ''}</td>
        <td>${r.sector ? r.sector.split(',').slice(0, 2).map(s => `<span class="tag">${esc(s.trim())}</span>`).join('') : '-'}</td>
        <td>${formatDate(r.date_reported)}</td>
        <td>${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">${r.source ? `<span class="source-badge ${esc(r.source)}">${esc(r.source)}</span>` : 'Link'}</a>` : (r.source ? `<span class="source-badge ${esc(r.source)}">${esc(r.source)}</span>` : '-')}</td>
      </tr>
    `).join('');

    const rp = $('roundsPagination');
    if (rp) renderPagination(data, 'roundsPagination', goToRoundsPage);
  } catch (err) {
    $('roundsTableBody').innerHTML = `<tr><td colspan="10" class="empty-state">Error: ${err.message}</td></tr>`;
  }
}

// ─── Pagination ───
function renderPagination(data, containerId, goToFn) {
  const container = $(containerId);
  if (!container) return;

  const { page, totalPages, total } = data;
  if (totalPages <= 1) {
    container.innerHTML = `<span class="page-info">${total} result${total !== 1 ? 's' : ''}</span>`;
    return;
  }

  let html = '';
  html += `<button ${page <= 1 ? 'disabled' : ''} onclick="${goToFn.name}(${page - 1})">Prev</button>`;
  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  if (start > 1) {
    html += `<button onclick="${goToFn.name}(1)">1</button>`;
    if (start > 2) html += `<span class="page-info">...</span>`;
  }
  for (let i = start; i <= end; i++) {
    html += `<button class="${i === page ? 'active' : ''}" onclick="${goToFn.name}(${i})">${i}</button>`;
  }
  if (end < totalPages) {
    if (end < totalPages - 1) html += `<span class="page-info">...</span>`;
    html += `<button onclick="${goToFn.name}(${totalPages})">${totalPages}</button>`;
  }
  html += `<button ${page >= totalPages ? 'disabled' : ''} onclick="${goToFn.name}(${page + 1})">Next</button>`;
  html += `<span class="page-info">${total} total</span>`;
  container.innerHTML = html;
}

window.goToPage = function(page) { currentPage = page; loadInvestors(); window.scrollTo({ top: 0, behavior: 'smooth' }); };
window.goToNewsPage = function(page) { newsPage = page; loadFundingNews(); };
window.goToRoundsPage = function(page) { roundsPage = page; loadFundingRounds(); };

// ─── Scrape Logs ───
async function loadScrapeLogs() {
  try {
    const res = await fetch('/api/scrape/logs');
    const logs = await res.json();
    const tbody = $('logsTableBody');

    if (logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No scrape runs yet. Use the Scrape News button to start.</td></tr>`;
      return;
    }

    tbody.innerHTML = logs.map(l => `
      <tr>
        <td><span class="source-badge ${esc(l.source)}">${esc(l.source)}</span></td>
        <td>${formatDateTime(l.started_at)}</td>
        <td>${l.finished_at ? formatDateTime(l.finished_at) : '-'}</td>
        <td><span class="status-badge ${esc(l.status)}">${esc(l.status)}</span></td>
        <td>${l.records_found}</td>
        <td>${l.new_records}</td>
        <td title="${esc(l.error_message || '')}">${esc((l.error_message || '').substring(0, 50))}</td>
      </tr>
    `).join('');
  } catch (err) {
    $('logsTableBody').innerHTML = `<tr><td colspan="7" class="empty-state">Error: ${err.message}</td></tr>`;
  }
}

// ─── Modal ───
function openModal(investor = null) {
  const form = $('investorForm');
  form.reset();
  if (investor) {
    $('modalTitle').textContent = 'Edit Investor';
    $('formId').value = investor.id;
    $('formName').value = investor.name || '';
    $('formInstitution').value = investor.institution || '';
    $('formTitle').value = investor.title || '';
    $('formCheque').value = investor.avg_cheque_size || '';
    $('formGeographies').value = investor.geographies || '';
    $('formSectors').value = investor.sectors || '';
    $('formStage').value = investor.stage || '';
    $('formShareholding').value = investor.shareholding || '';
    $('formEmail').value = investor.email || '';
    $('formWebsite').value = investor.website || '';
    $('formNotes').value = investor.notes || '';
  } else {
    $('modalTitle').textContent = 'Add Investor';
    $('formId').value = '';
  }
  $('investorModal').classList.remove('hidden');
}

function closeModal() { $('investorModal').classList.add('hidden'); }

window.editInvestor = async function(id) {
  try {
    const res = await fetch(`/api/investors/${id}`);
    const investor = await res.json();
    openModal(investor);
  } catch (err) { showToast('Error loading investor: ' + err.message, 'error'); }
};

window.removeInvestor = async function(id) {
  if (!confirm('Are you sure you want to delete this investor?')) return;
  try {
    await fetch(`/api/investors/${id}`, { method: 'DELETE' });
    showToast('Investor deleted', 'success');
    loadInvestors();
    loadStats();
  } catch (err) { showToast('Error deleting: ' + err.message, 'error'); }
};

async function saveInvestor() {
  const id = $('formId').value;
  const data = {
    name: $('formName').value,
    institution: $('formInstitution').value,
    title: $('formTitle').value,
    avg_cheque_size: $('formCheque').value,
    geographies: $('formGeographies').value,
    sectors: $('formSectors').value,
    stage: $('formStage').value,
    shareholding: $('formShareholding').value,
    email: $('formEmail').value,
    website: $('formWebsite').value,
    notes: $('formNotes').value
  };
  try {
    const url = id ? `/api/investors/${id}` : '/api/investors';
    const method = id ? 'PUT' : 'POST';
    const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    if (!res.ok) { const err = await res.json(); throw new Error(err.error); }
    showToast(id ? 'Investor updated' : 'Investor added', 'success');
    closeModal();
    loadInvestors();
    loadStats();
    loadFilters();
  } catch (err) { showToast('Error saving: ' + err.message, 'error'); }
}

// ─── Poll Scrape Status ───
function pollScrapeStatus(btn, originalHTML) {
  let attempts = 0;
  const maxAttempts = 120;
  const interval = setInterval(async () => {
    attempts++;
    if (attempts >= maxAttempts) { clearInterval(interval); btn.disabled = false; btn.innerHTML = originalHTML; return; }
    try {
      const res = await fetch('/api/scrape/logs');
      const logs = await res.json();
      if (logs.length > 0 && logs[0].status !== 'running') {
        clearInterval(interval);
        btn.disabled = false;
        btn.innerHTML = originalHTML;
        if (logs[0].status === 'completed') {
          showToast(`Scrape completed! Found ${logs[0].records_found} records (${logs[0].new_records} new)`, 'success');
        } else {
          showToast(`Scrape finished: ${logs[0].error_message || 'Check logs for details'}`, 'error');
        }
        loadStats();
        loadFilters();
        if (currentTab === 'news') loadFundingNews();
        if (currentTab === 'rounds') loadFundingRounds();
        if (currentTab === 'all' || currentTab === 'new') loadInvestors();
        if (currentTab === 'logs') loadScrapeLogs();
      }
    } catch (err) { /* ignore polling errors */ }
  }, 5000);
}

// ─── Utilities ───
function esc(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch { return dateStr; }
}

function formatDateTime(dateStr) {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr);
    return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return dateStr; }
}

function formatRelativeTime(date) {
  const now = new Date();
  const diff = now - date;
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(mins / 60);
  const days = Math.floor(hours / 24);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return formatDate(date.toISOString());
}

function showToast(message, type = '') {
  toast.textContent = message;
  toast.className = 'toast ' + type;
  setTimeout(() => { toast.className = 'toast hidden'; }, 4000);
}
