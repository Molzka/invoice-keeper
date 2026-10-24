(function () {
  var choice = 'system';
  try { var value = localStorage.getItem('invoice-keeper:theme'); if (value === 'light' || value === 'dark') choice = value; } catch { /* Fall back to the system theme when storage is restricted. */ }
  var dark = choice === 'dark' || choice === 'system' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var theme = dark ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
})();
