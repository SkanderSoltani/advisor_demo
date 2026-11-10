/* Clientside helpers (UI-only interactions). */
window.dash_clientside = Object.assign({}, window.dash_clientside, {
  ts: {
    focusOnOpen: function (opened, id) {
      if (opened) { setTimeout(function () { var el = document.getElementById(id); if (el) { el.focus(); } }, 60); }
      return window.dash_clientside.no_update;
    },
    togglePassword: function (n, type, cls) {
      const show = type === 'password';
      return [show ? 'text' : 'password', show ? 'Hide password' : 'Show password',
              'ts-input-trailing' + (show ? ' is-visible' : '')];
    },
  },
});
