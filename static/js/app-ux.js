/**
 * Stradit Workforce - Application UX Helper Library
 * Provides skeleton loaders, enhanced toast notifications, instant table filtering,
 * button pending states, and global keyboard shortcuts.
 */

window.EmpUX = (function () {
  'use strict';

  /**
   * Display enhanced toast notification
   * @param {string} message - Toast message text
   * @param {string} variant - 'success' | 'danger' | 'warning' | 'info'
   * @param {number} duration - Auto dismiss time in ms (default: 4000)
   */
  function showToast(message, variant, duration) {
    variant = variant || 'info';
    duration = duration || 4000;

    let toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) {
      toastContainer = document.createElement('div');
      toastContainer.id = 'toastContainer';
      toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
      toastContainer.style.zIndex = '1095';
      document.body.appendChild(toastContainer);
    }

    const iconMap = {
      success: 'bi-check-circle-fill',
      danger: 'bi-exclamation-triangle-fill',
      warning: 'bi-exclamation-circle-fill',
      info: 'bi-info-circle-fill'
    };

    const bgMap = {
      success: 'text-bg-success',
      danger: 'text-bg-danger',
      warning: 'text-bg-warning text-dark',
      info: 'text-bg-primary'
    };

    const toastEl = document.createElement('div');
    toastEl.className = `toast emp-toast align-items-center ${bgMap[variant] || 'text-bg-primary'} border-0 shadow-lg`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');

    toastEl.innerHTML = `
      <div class="d-flex align-items-center">
        <div class="toast-body d-flex align-items-center gap-2 py-3 px-3">
          <i class="bi ${iconMap[variant] || 'bi-info-circle'} fs-5"></i>
          <span class="fw-semibold">${message}</span>
        </div>
        <button type="button" class="btn-close btn-close-white me-3 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
      <div class="toast-progress-bar" style="animation-duration: ${duration}ms;"></div>
    `;

    toastContainer.appendChild(toastEl);

    if (window.bootstrap && window.bootstrap.Toast) {
      const bsToast = new window.bootstrap.Toast(toastEl, { delay: duration });
      bsToast.show();
      toastEl.addEventListener('hidden.bs.toast', function () {
        toastEl.remove();
      });
    } else {
      setTimeout(function () { toastEl.remove(); }, duration);
    }
  }

  /**
   * Render skeleton shimmer loading UI into container
   * @param {string|HTMLElement} target - Container element or selector
   * @param {string} type - 'card-grid' | 'table-rows' | 'profile'
   * @param {number} count - Number of items to render
   */
  function showSkeleton(target, type, count) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return;

    count = count || 3;
    let html = '';

    if (type === 'card-grid') {
      for (let i = 0; i < count; i++) {
        html += `
          <div class="col-md-6 col-lg-4 emp-skeleton-item">
            <div class="card h-100 p-4">
              <div class="emp-skeleton skeleton-avatar mb-3" style="width: 48px; height: 48px; border-radius: 12px;"></div>
              <div class="emp-skeleton skeleton-text mb-2" style="width: 60%; height: 20px;"></div>
              <div class="emp-skeleton skeleton-text mb-1" style="width: 90%; height: 14px;"></div>
              <div class="emp-skeleton skeleton-text" style="width: 75%; height: 14px;"></div>
            </div>
          </div>
        `;
      }
    } else if (type === 'table-rows') {
      for (let i = 0; i < count; i++) {
        html += `
          <tr class="emp-skeleton-item">
            <td colspan="10" class="py-3">
              <div class="d-flex align-items-center gap-3">
                <div class="emp-skeleton skeleton-avatar" style="width: 36px; height: 36px; border-radius: 50%;"></div>
                <div class="flex-grow-1">
                  <div class="emp-skeleton skeleton-text mb-1" style="width: 35%; height: 16px;"></div>
                  <div class="emp-skeleton skeleton-text" style="width: 20%; height: 12px;"></div>
                </div>
              </div>
            </td>
          </tr>
        `;
      }
    } else if (type === 'stat-grid') {
      for (let i = 0; i < count; i++) {
        html += `
          <div class="col-sm-6 col-lg-4 emp-skeleton-item">
            <div class="emp-stat-card">
              <div class="emp-skeleton skeleton-avatar" style="width: 48px; height: 48px; border-radius: 12px;"></div>
              <div class="flex-grow-1">
                <div class="emp-skeleton skeleton-text mb-2" style="width: 40%; height: 12px;"></div>
                <div class="emp-skeleton skeleton-text" style="width: 65%; height: 24px;"></div>
              </div>
            </div>
          </div>
        `;
      }
    }

    el.innerHTML = html;
  }

  /**
   * Set button loading spinner state
   * @param {string|HTMLElement} btnTarget - Button element or selector
   * @param {boolean} isLoading - Loading state
   * @param {string} loadingText - Text during loading
   */
  function setBtnLoading(btnTarget, isLoading, loadingText) {
    const btn = typeof btnTarget === 'string' ? document.querySelector(btnTarget) : btnTarget;
    if (!btn) return;

    if (isLoading) {
      btn.dataset.originalHtml = btn.innerHTML;
      btn.disabled = true;
      const text = loadingText || 'Processing...';
      btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${text}`;
    } else {
      btn.disabled = false;
      if (btn.dataset.originalHtml) {
        btn.innerHTML = btn.dataset.originalHtml;
      }
    }
  }

  /**
   * Attach instant client-side table filter to an input field
   * @param {string} inputSelector - Search input selector
   * @param {string} tableSelector - Target table tbody selector
   * @param {string} counterSelector - Optional element selector for row count display
   */
  function attachTableSearch(inputSelector, tableSelector, counterSelector) {
    const input = document.querySelector(inputSelector);
    const tbody = document.querySelector(tableSelector);
    if (!input || !tbody) return;

    input.addEventListener('input', function () {
      const query = input.value.toLowerCase().trim();
      const rows = tbody.querySelectorAll('tr:not(.emp-skeleton-item):not(.emp-empty-row)');
      let visibleCount = 0;

      rows.forEach(function (row) {
        const text = row.textContent.toLowerCase();
        if (!query || text.includes(query)) {
          row.style.display = '';
          visibleCount++;
        } else {
          row.style.display = 'none';
        }
      });

      if (counterSelector) {
        const counterEl = document.querySelector(counterSelector);
        if (counterEl) {
          counterEl.textContent = query ? `${visibleCount} match(es)` : `${rows.length} total`;
        }
      }
    });
  }

  /**
   * Setup global keyboard shortcuts
   */
  function initKeyboardShortcuts() {
    document.addEventListener('keydown', function (e) {
      // Ignore if user is inside an input, textarea, or contenteditable
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName) || document.activeElement.isContentEditable) {
        return;
      }

      // Press '/' to jump to primary search bar on page
      if (e.key === '/') {
        const searchInput = document.querySelector('input[type="search"], .emp-search-input, #tableSearch');
        if (searchInput) {
          e.preventDefault();
          searchInput.focus();
          searchInput.select();
        }
      }
    });
  }

  // Initialize shortcuts when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initKeyboardShortcuts);
  } else {
    initKeyboardShortcuts();
  }

  return {
    showToast: showToast,
    showSkeleton: showSkeleton,
    setBtnLoading: setBtnLoading,
    attachTableSearch: attachTableSearch
  };
})();
