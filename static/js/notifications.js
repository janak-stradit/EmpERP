(function () {
  const token = sessionStorage.getItem('access_token');
  if (!token) return;
  const authHeader = { Authorization: 'Bearer ' + token };

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
