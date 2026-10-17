/**
 * Theme toggle controller: Dark / Light monochrome
 */
(function () {
  const STORAGE_KEY = "nightly_vocab_theme";

  function getPreferredTheme() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") {
      return saved;
    }
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEY, theme);
    const themeBtn = document.getElementById("theme-toggle-btn");
    if (themeBtn) {
      themeBtn.textContent = theme === "dark" ? "☀️" : "🌙";
      themeBtn.setAttribute("aria-label", theme === "dark" ? "تغییر به تم روشن" : "تغییر به تم تیره");
    }
  }

  window.toggleTheme = function () {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
  };

  // Immediate execution to prevent flash
  applyTheme(getPreferredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(getPreferredTheme());
  });
})();
