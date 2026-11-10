/* AG Grid value formatters — same rules as services/format.py */
var dagfuncs = (window.dashAgGridFunctions = window.dashAgGridFunctions || {});
dagfuncs.money = function (v) {
  if (v === null || v === undefined || v === '') return '—';
  var s = v < 0 ? '-' : '', a = Math.abs(v);
  if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(2) + 'M';
  return s + '$' + Math.round(a).toLocaleString('en-US');
};
dagfuncs.moneyFull = function (v) {
  if (v === null || v === undefined || v === '') return '—';
  return (v < 0 ? '-$' : '$') + Math.round(Math.abs(v)).toLocaleString('en-US');
};
dagfuncs.signedMoney = function (v) {
  if (v === null || v === undefined || v === '') return '—';
  return (v >= 0 ? '+$' : '-$') + Math.round(Math.abs(v)).toLocaleString('en-US');
};
dagfuncs.pct = function (v, d) {
  if (v === null || v === undefined || v === '') return '—';
  return (v * 100).toFixed(d === undefined ? 2 : d) + '%';
};
dagfuncs.num = function (v, d) {
  if (v === null || v === undefined || v === '') return '—';
  return Number(v).toLocaleString('en-US', {minimumFractionDigits: d || 0, maximumFractionDigits: d || 0});
};
dagfuncs.dash = function (v) { return v === null || v === undefined || v === '' ? '—' : v; };
