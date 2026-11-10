// Live Plaid Link (sandbox mode only). Mock mode never loads this script from the CDN:
// the backend returns mock_public_token and the exchange happens server-side.
window.tsPlaid = {
  open: function (linkToken) {
    function launch() {
      var handler = window.Plaid.create({
        token: linkToken,
        onSuccess: function (publicToken) {
          window.dash_clientside.set_props('ws-plaid-public', { data: publicToken });
        },
        onExit: function () { handler.destroy(); },
      });
      handler.open();
    }
    if (window.Plaid) return launch();
    var s = document.createElement('script');
    s.src = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js';
    s.onload = launch;
    document.head.appendChild(s);
  },
};
