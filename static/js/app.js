/**
 * A-Share Analysis System — Minimal client-side JavaScript
 *
 * Handles:
 * - Theme toggle (light/dark)
 * - Chart container resize on window resize
 * - htmx event hooks
 */

// ============================================================
// Theme Toggle
// ============================================================

/**
 * Toggle between astock (light) and astock-dark themes.
 * Persists the choice in localStorage.
 */
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'astock' ? 'astock-dark' : 'astock';

  html.setAttribute('data-theme', next);
  localStorage.setItem('astock-theme', next);

  // Sync the toggle checkbox state
  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.checked = next === 'astock-dark';
  }
}

/**
 * Restore saved theme on page load.
 */
function restoreTheme() {
  const saved = localStorage.getItem('astock-theme');
  if (saved) {
    document.documentElement.setAttribute('data-theme', saved);
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.checked = saved === 'astock-dark';
    }
  }
}

// ============================================================
// Chart Resize
// ============================================================

/** Debounce helper. */
function debounce(fn, delay) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

/**
 * Trigger Plotly relayout on all visible charts when window resizes.
 */
const handleResize = debounce(function () {
  if (typeof Plotly !== 'undefined') {
    const charts = document.querySelectorAll('.js-plotly-plot');
    charts.forEach(function (chart) {
      Plotly.Plots.resize(chart);
    });
  }
}, 250);

// ============================================================
// htmx Events
// ============================================================

/** After htmx swaps in new content, resize any Plotly charts. */
document.addEventListener('htmx:afterSwap', function () {
  // Small delay to let the DOM settle
  setTimeout(handleResize, 100);
});

// ============================================================
// Init
// ============================================================

document.addEventListener('DOMContentLoaded', function () {
  restoreTheme();
  window.addEventListener('resize', handleResize);
});
