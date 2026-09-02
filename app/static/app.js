(() => {
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const message = form.getAttribute('data-confirm') || '确认继续？';
      if (!window.confirm(message)) event.preventDefault();
    });
  });
  if (document.body.dataset.autoRefresh === 'true') {
    window.setTimeout(() => window.location.reload(), 3500);
  }
})();
