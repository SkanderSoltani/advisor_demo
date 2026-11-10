/* AG Grid cell renderers (React, via Dash's global React/ReactDOM). */
var dagcomponentfuncs = (window.dashAgGridComponentFunctions = window.dashAgGridComponentFunctions || {});
var h = React.createElement;

var STATUS = {
  on_target: ['On target', 'ts-pill ts-pill--positive'],
  drifting: ['Drifting', 'ts-pill ts-pill--warning'],
  needs_review: ['Needs review', 'ts-pill ts-pill--negative'],
  onboarding: ['Onboarding', 'ts-pill ts-pill--neutral'],
};
var CLIENT_TYPE = { individual: 'Individual', couple: 'Joint', family: 'Family', trust: 'Trust' };

dagcomponentfuncs.StatusPill = function (props) {
  var s = STATUS[props.value] || [props.value, 'ts-pill ts-pill--neutral'];
  return h('span', { className: s[1] }, s[0]);
};

dagcomponentfuncs.ClientName = function (props) {
  var d = props.data;
  return h('div', { className: 'ts-cell-stack' },
    h('button', {
      className: 'ts-cell-link', type: 'button',
      onClick: function () { props.setData({ action: 'view', id: d.id, ts: Date.now() }); },
    }, d.name),
    h('p', { className: 'ts-cell-sub' }, CLIENT_TYPE[d.client_type] || d.client_type));
};

dagcomponentfuncs.ModelChips = function (props) {
  var v = props.value || [];
  if (!v.length) return h('span', { className: 'ts-c-ink600' }, '—');
  return h('span', { className: 'ts-row ts-gap-1' },
    v.map(function (m) { return h('span', { key: m, className: 'ts-chip' }, m); }));
};

dagcomponentfuncs.Signed = function (props) {
  var v = props.value;
  if (v === null || v === undefined) return '—';
  var pos = v >= 0;
  return h('span', { className: 'ts-signed ' + (pos ? 'ts-c-positive' : 'ts-c-negative') },
    h('span', { 'aria-hidden': 'true' }, pos ? '▲' : '▼'),
    window.dashAgGridFunctions.signedMoney(v));
};

dagcomponentfuncs.RowMenu = function (props) {
  var st = React.useState(null), pos = st[0], setPos = st[1];
  var d = props.data;
  var items = props.items || [['view', 'View client'], ['add_account', 'Add account'], ['start', 'Start transition'], ['delete', 'Delete client']];
  React.useEffect(function () {
    if (!pos) return;
    var close = function (e) { if (!e.target.closest || !e.target.closest('.ts-menu')) setPos(null); };
    var esc = function (e) { if (e.key === 'Escape') setPos(null); };
    document.addEventListener('mousedown', close); document.addEventListener('keydown', esc);
    var wheel = function () { setPos(null); };
    window.addEventListener('wheel', wheel, { passive: true }); window.addEventListener('touchmove', wheel, { passive: true });
    return function () {
      document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc);
      window.removeEventListener('wheel', wheel); window.removeEventListener('touchmove', wheel);
    };
  }, [pos]);
  var btn = h('button', {
    type: 'button', className: 'ts-menu-trigger', 'aria-label': 'Actions for ' + (d.name || d.id),
    'aria-expanded': !!pos, 'aria-haspopup': 'menu',
    onClick: function (e) { var r = e.currentTarget.getBoundingClientRect(); setPos(pos ? null : { x: r.right, y: r.bottom }); },
  }, h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' },
    h('circle', { cx: 12, cy: 12, r: 1 }), h('circle', { cx: 19, cy: 12, r: 1 }), h('circle', { cx: 5, cy: 12, r: 1 })));
  var menu = pos && ReactDOM.createPortal(h('div', {
    className: 'ts-menu', role: 'menu', style: { top: pos.y + 6, left: pos.x - 176 },
  }, items.map(function (it, i) {
    return h('button', {
      key: it[0], type: 'button', role: 'menuitem', autoFocus: i === 0,
      className: 'ts-menu-item' + (it[0] === 'start' ? ' is-accent' : '') + (it[0] === 'delete' ? ' is-danger' : ''),
      onClick: function () { setPos(null); props.setData({ action: it[0], id: d.id, ts: Date.now() }); },
    }, it[1]);
  })), document.body);
  return h(React.Fragment, null, btn, menu);
};

dagcomponentfuncs.ActionLink = function (props) {
  var d = props.data;
  var label = props.label || (d.n_lots ? 'Start transition' : 'Import & start transition');
  return h('button', {
    type: 'button', className: 'ts-action-link',
    onClick: function () { props.setData({ action: props.action || 'start', id: d.id, ts: Date.now() }); },
  }, label, h('span', { 'aria-hidden': 'true' }, ' →'));
};

dagcomponentfuncs.TermBadge = function (props) {
  if (!props.value) return h('span', { className: 'ts-c-ink600' }, '—');
  return h('span', { className: 'ts-term' }, props.value);
};
