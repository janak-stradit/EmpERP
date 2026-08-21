(function () {
  const token = sessionStorage.getItem('access_token');
  if (!token) return;
  const authHeader = { Authorization: 'Bearer ' + token };

  // ---- Keep every request authenticated with the freshest token ----
  // Every page captures its own `authHeader`/`token` once, as a const, at load time.
  // Access tokens are short-lived (~15 min); without this, a page left open longer
  // than that starts sending a stale token on every request and users see
  // "Invalid or expired token" until they reload. This patches both request paths
  // used across the app (jQuery's $.ajax and raw fetch) to always attach whatever
  // token currently lives in sessionStorage, and refreshes it in the background
  // before it expires.

  if (window.jQuery && !window.jQuery._empAuthPrefilterInstalled) {
    window.jQuery._empAuthPrefilterInstalled = true;
    window.jQuery.ajaxPrefilter(function (options) {
      const current = sessionStorage.getItem('access_token');
      if (current) {
        options.headers = options.headers || {};
        options.headers.Authorization = 'Bearer ' + current;
      }
    });
  }

  if (!window._empFetchPatched) {
    window._empFetchPatched = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init || {};
      const hasAuthHeader = init.headers && (
        (init.headers instanceof Headers && init.headers.has('Authorization')) ||
        (typeof init.headers.Authorization !== 'undefined')
      );
      if (hasAuthHeader) {
        const current = sessionStorage.getItem('access_token');
        if (current) {
          if (init.headers instanceof Headers) {
            init.headers.set('Authorization', 'Bearer ' + current);
          } else {
            init = Object.assign({}, init, { headers: Object.assign({}, init.headers, { Authorization: 'Bearer ' + current }) });
          }
        }
      }
      return originalFetch(input, init);
    };
  }

  let refreshInFlight = null;

  function refreshAccessToken() {
    if (refreshInFlight) return refreshInFlight;
    const refreshToken = sessionStorage.getItem('refresh_token');
    if (!refreshToken) return Promise.reject(new Error('no refresh token'));
    refreshInFlight = window.fetch('/api/v1/auth/refresh', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: refreshToken })
    })
      .then(function (r) { if (!r.ok) throw new Error('refresh failed'); return r.json(); })
      .then(function (data) {
        sessionStorage.setItem('access_token', data.access_token);
        sessionStorage.setItem('refresh_token', data.refresh_token);
      })
      .finally(function () { refreshInFlight = null; });
    return refreshInFlight;
  }

  // Proactively refresh well before the access token's ~360 minute (6 hour) expiry.
  setInterval(function () { refreshAccessToken().catch(function () {}); }, 60 * 60 * 1000);

  // Fallback: if a request still 401s (e.g. a long-backgrounded tab where timers
  // were throttled), try one silent refresh; only force a re-login if the
  // refresh token itself is dead.
  if (window.jQuery && !window.jQuery._empAuthErrorHandlerInstalled) {
    window.jQuery._empAuthErrorHandlerInstalled = true;
    window.jQuery(document).ajaxError(function (event, jqXHR, ajaxSettings) {
      if (jqXHR.status !== 401) return;
      if (ajaxSettings.url && ajaxSettings.url.indexOf('/auth/refresh') !== -1) return;
      refreshAccessToken().catch(function () {
        sessionStorage.clear();
        window.location.href = '/auth/login';
      });
    });
  }

  function timeAgo(iso) {
    const diffSeconds = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diffSeconds < 60) return 'just now';
    if (diffSeconds < 3600) return Math.floor(diffSeconds / 60) + 'm ago';
    if (diffSeconds < 86400) return Math.floor(diffSeconds / 3600) + 'h ago';
    return Math.floor(diffSeconds / 86400) + 'd ago';
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : value;
    return div.innerHTML;
  }

  function injectBell() {
    const nav = document.querySelector('.emp-navbar-collapse') || document.querySelector('.navbar-nav');
    if (!nav || document.getElementById('notifBellItem')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'nav-item dropdown';
    wrapper.id = 'notifBellItem';
    wrapper.innerHTML =
      '<a class="nav-link position-relative" href="#" id="notifBellToggle" role="button" data-bs-toggle="dropdown" aria-expanded="false">' +
        '<i class="bi bi-bell"></i>' +
        '<span class="badge rounded-pill bg-danger d-none" id="notifBadge">0</span>' +
      '</a>' +
      '<div class="dropdown-menu dropdown-menu-end p-0 shadow emp-notif-dropdown" id="notifDropdown">' +
        '<div class="d-flex justify-content-between align-items-center px-3 py-2 border-bottom">' +
          '<strong class="small">Notifications</strong>' +
          '<button type="button" class="btn btn-sm btn-link p-0 text-decoration-none" id="notifMarkAllBtn">Mark all read</button>' +
        '</div>' +
        '<div id="notifList"></div>' +
        '<div class="text-center text-muted small py-4 d-none" id="notifEmptyState">No notifications yet.</div>' +
      '</div>';

    const logoutLink = document.getElementById('logoutLink');
    if (logoutLink && logoutLink.parentElement === nav) {
      nav.insertBefore(wrapper, logoutLink);
    } else {
      nav.appendChild(wrapper);
    }
  }

  function renderList(items) {
    const list = document.getElementById('notifList');
    const empty = document.getElementById('notifEmptyState');
    if (!list || !empty) return;
    empty.classList.toggle('d-none', items.length > 0);
    list.innerHTML = items.map(function (n) {
      const href = n.link || '#';
      const unreadClass = n.is_read ? '' : ' emp-notif-unread';
      return '<a href="' + href + '" class="dropdown-item notif-item py-2 border-bottom' + unreadClass + '" data-id="' + n.id + '">' +
        '<div class="fw-semibold small">' + escapeHtml(n.title) + '</div>' +
        (n.body ? '<div class="text-muted small">' + escapeHtml(n.body) + '</div>' : '') +
        '<div class="text-muted" style="font-size: 0.7rem;">' + timeAgo(n.created_at) + '</div>' +
      '</a>';
    }).join('');
  }

  function loadCount() {
    fetch('/api/v1/notifications/unread-count', { headers: authHeader })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        const badge = document.getElementById('notifBadge');
        if (!badge) return;
        badge.classList.toggle('d-none', data.count === 0);
        badge.textContent = data.count > 9 ? '9+' : String(data.count);
      })
      .catch(function () {});
  }

  function loadList() {
    fetch('/api/v1/notifications?limit=20', { headers: authHeader })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(renderList)
      .catch(function () {});
  }

  function init() {
    injectBell();
    loadCount();

    const toggle = document.getElementById('notifBellToggle');
    if (toggle) toggle.addEventListener('click', loadList);

    document.addEventListener('click', function (e) {
      const item = e.target.closest('.notif-item');
      if (!item) return;
      const id = item.getAttribute('data-id');
      fetch('/api/v1/notifications/' + id + '/read', { method: 'POST', headers: authHeader }).then(loadCount);
    });

    document.addEventListener('click', function (e) {
      if (e.target && e.target.id === 'notifMarkAllBtn') {
        e.preventDefault();
        fetch('/api/v1/notifications/read-all', { method: 'POST', headers: authHeader }).then(function () {
          loadCount();
          loadList();
        });
      }
    });

    setInterval(loadCount, 30000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
