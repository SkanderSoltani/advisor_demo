/* Clientside helpers (UI-only interactions). */
window.dash_clientside = Object.assign({}, window.dash_clientside, {
  ts: {
    /* Analytics tabs: every pane is rendered once; hidden panes keep their full width (height 0)
       so their charts are laid out at the right size before they are shown (no resize flash).
       The area keeps just enough height to reach the bottom of the visible workspace, so a
       shorter tab never pulls the view up, and that filler shrinks away as you scroll back up. */
    switchTab: function (boxSel, tab, ids) {
      const box = document.querySelector(boxSel);
      const canvas = box && box.closest('.ts-canvas');
      if (box && canvas) {
        const fill = function () {
          const need = canvas.getBoundingClientRect().bottom - box.getBoundingClientRect().top;
          return Math.max(0, Math.round(need));
        };
        box.style.minHeight = fill() + 'px';
        if (!box.dataset.tsFill) {
          box.dataset.tsFill = '1';
          canvas.addEventListener('scroll', function () {
            const cur = parseFloat(box.style.minHeight) || 0;
            const need = fill();
            if (need < cur) { box.style.minHeight = need + 'px'; }
          }, {passive: true});
        }
      }
      return ids.map(function (i) { return i.id === tab ? {} : window.dash_clientside.ts.HIDDEN; });
    },
    HIDDEN: {height: '0', overflow: 'hidden', visibility: 'hidden'},
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
