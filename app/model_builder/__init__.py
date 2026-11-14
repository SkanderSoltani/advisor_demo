"""Model Builder: build a model (import a file or pick tickers), analyse it, refine it, scale it
into a line of models by equity exposure and save the line to the model catalog.

Everything here is a demo on the synthetic market: characteristics such as duration, ratings,
P/E or P/B are mock reference data (``reference.py``); risk comes from the mock risk provider and
the hypothetical performance from the simulated prices. Swap ``reference.py`` and the provider
for Aladdin / Bloomberg data later.
"""
