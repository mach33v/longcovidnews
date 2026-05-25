const CATS = ['research','legal','policy','treatment','community'];

function formatDate(iso) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
}

function slug(article) {
  return article.slug || article.title.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
}

function badge(cat) {
  return `<span class="badge badge-${cat}">${cat}</span>`;
}

function renderList(articles, cat) {
  const filtered = cat ? articles.filter(a => a.category === cat) : articles;
  const catLabel = cat ? cat.charAt(0).toUpperCase() + cat.slice(1) : null;

  return `
    <div class="page-header">
      <h1>${catLabel ? catLabel + ' News' : 'Latest Coverage'}</h1>
      <p>${filtered.length} article${filtered.length !== 1 ? 's' : ''}${cat ? ' in ' + catLabel : ''} · Updated daily</p>
    </div>
    ${filtered.length === 0
      ? '<div class="empty">No articles yet. Check back tomorrow.</div>'
      : `<div class="article-grid">${filtered.map(a => `
          <div class="article-card" onclick="navigate('?article=${slug(a)}')">
            <div class="card-meta">
              ${badge(a.category)}
              <span class="card-date">${formatDate(a.date)}</span>
            </div>
            <h2>${a.title}</h2>
            <p>${a.excerpt || a.body.replace(/<[^>]+>/g,'').slice(0,180)}…</p>
            <span class="read-more">Read more →</span>
          </div>`).join('')}
        </div>`
    }`;
}

function renderArticle(articles, articleSlug) {
  const a = articles.find(x => slug(x) === articleSlug);
  if (!a) return '<div class="empty">Article not found. <a href="/">← Back to home</a></div>';

  return `
    <div class="article-detail">
      <a class="back-link" href="/">← All articles</a>
      <div class="article-meta">
        ${badge(a.category)}
        <span class="card-date">${formatDate(a.date)}</span>
      </div>
      <h1>${a.title}</h1>
      <div class="article-body">${a.body}</div>
      ${a.source_url ? `<a class="source-link" href="${a.source_url}" target="_blank" rel="noopener">
        View source article ↗
      </a>` : ''}
    </div>`;
}

function navigate(url) {
  window.history.pushState({}, '', url);
  render();
}

async function render() {
  const app = document.getElementById('app');
  const params = new URLSearchParams(window.location.search);
  const articleSlug = params.get('article');
  const cat = params.get('cat');

  // Highlight active nav
  document.querySelectorAll('nav a').forEach(a => {
    const href = new URLSearchParams(new URL(a.href, location.origin).search).get('cat');
    a.classList.toggle('active', href === cat && !articleSlug);
  });

  try {
    const res = await fetch('/articles.json?t=' + Date.now());
    const articles = await res.json();

    app.innerHTML = articleSlug
      ? renderArticle(articles, articleSlug)
      : renderList(articles, cat);
  } catch {
    app.innerHTML = '<div class="empty">Unable to load articles.</div>';
  }
}

window.addEventListener('popstate', render);
render();
