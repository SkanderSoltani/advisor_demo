"""Point-in-time portfolio analytics: allocation, exposures and risk for the book and each client.

Layout (everything a data vendor touches lives in this folder):

* ``types.py``         – vendor-neutral inputs (``Portfolio``) and the report (``RiskReport``).
* ``provider.py``      – the ``RiskAnalyticsProvider`` interface every source implements.
* ``mock_provider.py`` – simulated numbers from the synthetic market (the only working source).
* ``aladdin_provider.py`` / ``bloomberg_provider.py`` – stubs with TODOs for the real feeds.
* ``security_master.py`` – mock reference data (asset class, GICS sector, country), generated once.
* ``snapshot.py``      – stores every report in ``data/analytics/risk_snapshot.json`` so numbers
  are generated once and then read back (never re-generated on each login).
* ``service.py``       – builds portfolios from the database and serves cached reports.
* ``factory.py``       – picks the provider from ``RISK_ANALYTICS_PROVIDER``
  (mock | aladdin | bloomberg).

To connect a real source: implement the three methods of ``RiskAnalyticsProvider`` in the matching
stub, set ``RISK_ANALYTICS_PROVIDER``, and press "Recalculate" (or delete the snapshot file).
"""
