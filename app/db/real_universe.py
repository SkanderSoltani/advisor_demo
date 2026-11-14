"""Real company names for the synthetic stock universe.

The synthetic market draws each stock's sector, size and price path at random; these lists only
supply the *label*. Within a sector, the largest simulated stock takes the first name in the list,
the next largest the second, and so on (lists are roughly in order of real market cap). Prices,
returns, dividends and fundamentals stay simulated: they are not the real companies' data.

Every stock gets a real company: there are no made-up names.
Each entry: (ticker, name, country). Non-US companies are their US-listed ADRs / shares.
Single-letter tickers that read as words (A, O) are left out so chat text isn't misread.
"""

from __future__ import annotations

US = "United States"

REAL_STOCKS: dict[str, list[tuple[str, str, str]]] = {
    "Information Technology": [
        ("AAPL", "Apple Inc.", US), ("MSFT", "Microsoft Corp.", US),
        ("NVDA", "NVIDIA Corp.", US), ("AVGO", "Broadcom Inc.", US),
        ("TSM", "Taiwan Semiconductor Manufacturing", "Taiwan"), ("ORCL", "Oracle Corp.", US),
        ("CRM", "Salesforce Inc.", US), ("ASML", "ASML Holding", "Netherlands"),
        ("AMD", "Advanced Micro Devices", US), ("CSCO", "Cisco Systems", US),
        ("IBM", "International Business Machines", US), ("ADBE", "Adobe Inc.", US),
        ("ACN", "Accenture plc", US), ("NOW", "ServiceNow Inc.", US),
        ("INTU", "Intuit Inc.", US), ("TXN", "Texas Instruments", US),
        ("QCOM", "Qualcomm Inc.", US), ("PLTR", "Palantir Technologies", US),
        ("AMAT", "Applied Materials", US), ("SAP", "SAP SE", "Germany"),
        ("MU", "Micron Technology", US), ("LRCX", "Lam Research", US),
        ("KLAC", "KLA Corp.", US), ("ADI", "Analog Devices", US),
        ("SHOP", "Shopify Inc.", "Canada"), ("PANW", "Palo Alto Networks", US),
        ("ANET", "Arista Networks", US), ("CRWD", "CrowdStrike Holdings", US),
        ("SNPS", "Synopsys Inc.", US), ("CDNS", "Cadence Design Systems", US),
        ("APH", "Amphenol Corp.", US), ("INTC", "Intel Corp.", US),
        ("MSI", "Motorola Solutions", US), ("FTNT", "Fortinet Inc.", US),
        ("DELL", "Dell Technologies", US), ("ADSK", "Autodesk Inc.", US),
        ("WDAY", "Workday Inc.", US), ("ROP", "Roper Technologies", US),
        ("NXPI", "NXP Semiconductors", "Netherlands"), ("INFY", "Infosys Ltd.", "India"),
        ("MCHP", "Microchip Technology", US), ("GLW", "Corning Inc.", US),
        ("HPQ", "HP Inc.", US), ("CTSH", "Cognizant Technology Solutions", US),
        ("IT", "Gartner Inc.", US),
    ],
    "Health Care": [
        ("LLY", "Eli Lilly and Co.", US), ("UNH", "UnitedHealth Group", US),
        ("JNJ", "Johnson & Johnson", US), ("ABBV", "AbbVie Inc.", US),
        ("NVO", "Novo Nordisk", "Denmark"), ("MRK", "Merck & Co.", US),
        ("AZN", "AstraZeneca plc", "United Kingdom"), ("NVS", "Novartis AG", "Switzerland"),
        ("TMO", "Thermo Fisher Scientific", US), ("ABT", "Abbott Laboratories", US),
        ("ISRG", "Intuitive Surgical", US), ("AMGN", "Amgen Inc.", US),
        ("DHR", "Danaher Corp.", US), ("PFE", "Pfizer Inc.", US),
        ("SYK", "Stryker Corp.", US), ("BSX", "Boston Scientific", US),
        ("GILD", "Gilead Sciences", US), ("VRTX", "Vertex Pharmaceuticals", US),
        ("MDT", "Medtronic plc", US), ("BMY", "Bristol-Myers Squibb", US),
        ("SNY", "Sanofi", "France"), ("ELV", "Elevance Health", US),
        ("CI", "The Cigna Group", US), ("REGN", "Regeneron Pharmaceuticals", US),
        ("GSK", "GSK plc", "United Kingdom"), ("ZTS", "Zoetis Inc.", US),
        ("MCK", "McKesson Corp.", US), ("CVS", "CVS Health", US),
        ("HCA", "HCA Healthcare", US), ("BDX", "Becton, Dickinson and Co.", US),
        ("COR", "Cencora Inc.", US), ("EW", "Edwards Lifesciences", US),
        ("IDXX", "IDEXX Laboratories", US), ("TAK", "Takeda Pharmaceutical", "Japan"),
        ("IQV", "IQVIA Holdings", US), ("GEHC", "GE HealthCare Technologies", US),
        ("RMD", "ResMed Inc.", US), ("HUM", "Humana Inc.", US),
        ("DXCM", "DexCom Inc.", US), ("CNC", "Centene Corp.", US),
        ("BIIB", "Biogen Inc.", US), ("ZBH", "Zimmer Biomet", US),
        ("STE", "STERIS plc", US), ("WAT", "Waters Corp.", US),
        ("MTD", "Mettler-Toledo International", US), ("LH", "Labcorp Holdings", US),
        ("DGX", "Quest Diagnostics", US), ("PODD", "Insulet Corp.", US),
        ("HOLX", "Hologic Inc.", US), ("BAX", "Baxter International", US),
        ("ILMN", "Illumina Inc.", US), ("ALGN", "Align Technology", US),
        ("INCY", "Incyte Corp.", US), ("MRNA", "Moderna Inc.", US),
        ("WST", "West Pharmaceutical Services", US),
    ],
    "Financials": [
        ("JPM", "JPMorgan Chase & Co.", US), ("V", "Visa Inc.", US),
        ("MA", "Mastercard Inc.", US), ("BAC", "Bank of America", US),
        ("WFC", "Wells Fargo & Co.", US), ("GS", "Goldman Sachs Group", US),
        ("MS", "Morgan Stanley", US), ("AXP", "American Express", US),
        ("HSBC", "HSBC Holdings", "United Kingdom"), ("RY", "Royal Bank of Canada", "Canada"),
        ("SPGI", "S&P Global Inc.", US), ("BLK", "BlackRock Inc.", US),
        ("C", "Citigroup Inc.", US), ("SCHW", "Charles Schwab Corp.", US),
        ("MUFG", "Mitsubishi UFJ Financial Group", "Japan"), ("PGR", "Progressive Corp.", US),
        ("CB", "Chubb Ltd.", US), ("BX", "Blackstone Inc.", US),
        ("HDB", "HDFC Bank", "India"), ("MMC", "Marsh & McLennan", US),
        ("KKR", "KKR & Co.", US), ("ICE", "Intercontinental Exchange", US),
        ("CME", "CME Group", US), ("TD", "Toronto-Dominion Bank", "Canada"),
        ("PYPL", "PayPal Holdings", US), ("COF", "Capital One Financial", US),
        ("USB", "U.S. Bancorp", US), ("PNC", "PNC Financial Services", US),
        ("AON", "Aon plc", US), ("MCO", "Moody's Corp.", US),
        ("BK", "Bank of New York Mellon", US), ("TRV", "Travelers Companies", US),
        ("AJG", "Arthur J. Gallagher & Co.", US), ("AFL", "Aflac Inc.", US),
        ("MET", "MetLife Inc.", US), ("TFC", "Truist Financial", US),
        ("ALL", "Allstate Corp.", US), ("AIG", "American International Group", US),
        ("PRU", "Prudential Financial", US), ("MSCI", "MSCI Inc.", US),
        ("AMP", "Ameriprise Financial", US), ("NDAQ", "Nasdaq Inc.", US),
        ("STT", "State Street Corp.", US), ("RJF", "Raymond James Financial", US),
        ("FITB", "Fifth Third Bancorp", US), ("TROW", "T. Rowe Price Group", US),
    ],
    "Consumer Discretionary": [
        ("AMZN", "Amazon.com Inc.", US), ("TSLA", "Tesla Inc.", US),
        ("HD", "Home Depot", US), ("TM", "Toyota Motor Corp.", "Japan"),
        ("BABA", "Alibaba Group", "China"), ("MCD", "McDonald's Corp.", US),
        ("BKNG", "Booking Holdings", US), ("LOW", "Lowe's Companies", US),
        ("TJX", "TJX Companies", US), ("SONY", "Sony Group Corp.", "Japan"),
        ("PDD", "PDD Holdings", "China"), ("MELI", "MercadoLibre Inc.", "Brazil"),
        ("SBUX", "Starbucks Corp.", US), ("NKE", "Nike Inc.", US),
        ("ABNB", "Airbnb Inc.", US), ("ORLY", "O'Reilly Automotive", US),
        ("DASH", "DoorDash Inc.", US), ("CMG", "Chipotle Mexican Grill", US),
        ("MAR", "Marriott International", US), ("AZO", "AutoZone Inc.", US),
        ("HLT", "Hilton Worldwide", US), ("GM", "General Motors", US),
        ("RCL", "Royal Caribbean Group", US), ("ROST", "Ross Stores", US),
        ("F", "Ford Motor Co.", US), ("HMC", "Honda Motor Co.", "Japan"),
        ("DHI", "D.R. Horton", US), ("YUM", "Yum! Brands", US),
        ("LULU", "Lululemon Athletica", "Canada"), ("LEN", "Lennar Corp.", US),
        ("EBAY", "eBay Inc.", US), ("CCL", "Carnival Corp.", US),
        ("GRMN", "Garmin Ltd.", US), ("TSCO", "Tractor Supply Co.", US),
        ("DECK", "Deckers Outdoor", US), ("PHM", "PulteGroup Inc.", US),
        ("EXPE", "Expedia Group", US), ("NVR", "NVR Inc.", US),
        ("ULTA", "Ulta Beauty", US), ("LVS", "Las Vegas Sands", US),
        ("DRI", "Darden Restaurants", US), ("GPC", "Genuine Parts Co.", US),
        ("BBY", "Best Buy Co.", US), ("DPZ", "Domino's Pizza", US),
        ("RL", "Ralph Lauren Corp.", US), ("TPR", "Tapestry Inc.", US),
        ("APTV", "Aptiv plc", US), ("POOL", "Pool Corp.", US),
        ("WYNN", "Wynn Resorts", US), ("MGM", "MGM Resorts International", US),
        ("KMX", "CarMax Inc.", US), ("LKQ", "LKQ Corp.", US),
        ("HAS", "Hasbro Inc.", US), ("RIVN", "Rivian Automotive", US),
    ],
    "Communication Services": [
        ("GOOGL", "Alphabet Inc.", US), ("META", "Meta Platforms", US),
        ("NFLX", "Netflix Inc.", US), ("TMUS", "T-Mobile US", US),
        ("DIS", "Walt Disney Co.", US), ("T", "AT&T Inc.", US),
        ("VZ", "Verizon Communications", US), ("CMCSA", "Comcast Corp.", US),
        ("SPOT", "Spotify Technology", "Sweden"), ("BIDU", "Baidu Inc.", "China"),
        ("NTES", "NetEase Inc.", "China"), ("SE", "Sea Ltd.", "Singapore"),
        ("CHTR", "Charter Communications", US), ("EA", "Electronic Arts", US),
        ("TTWO", "Take-Two Interactive", US), ("RBLX", "Roblox Corp.", US),
        ("WBD", "Warner Bros. Discovery", US), ("LYV", "Live Nation Entertainment", US),
        ("OMC", "Omnicom Group", US), ("TKO", "TKO Group Holdings", US),
        ("FOXA", "Fox Corp.", US), ("BCE", "BCE Inc.", "Canada"),
        ("VOD", "Vodafone Group", "United Kingdom"), ("PINS", "Pinterest Inc.", US),
        ("NWSA", "News Corp.", US), ("NYT", "New York Times Co.", US),
        ("SNAP", "Snap Inc.", US), ("ROKU", "Roku Inc.", US),
        ("MTCH", "Match Group", US), ("SIRI", "Sirius XM Holdings", US),
    ],
    "Industrials": [
        ("GE", "GE Aerospace", US), ("CAT", "Caterpillar Inc.", US),
        ("RTX", "RTX Corp.", US), ("UBER", "Uber Technologies", US),
        ("HON", "Honeywell International", US), ("UNP", "Union Pacific", US),
        ("ETN", "Eaton Corp.", US), ("BA", "Boeing Co.", US),
        ("DE", "Deere & Co.", US), ("LMT", "Lockheed Martin", US),
        ("ADP", "Automatic Data Processing", US), ("GD", "General Dynamics", US),
        ("UPS", "United Parcel Service", US), ("WM", "Waste Management", US),
        ("NOC", "Northrop Grumman", US), ("TT", "Trane Technologies", US),
        ("PH", "Parker-Hannifin", US), ("ITW", "Illinois Tool Works", US),
        ("MMM", "3M Co.", US), ("CNI", "Canadian National Railway", "Canada"),
        ("CTAS", "Cintas Corp.", US), ("EMR", "Emerson Electric", US),
        ("CSX", "CSX Corp.", US), ("CP", "Canadian Pacific Kansas City", "Canada"),
        ("FDX", "FedEx Corp.", US), ("NSC", "Norfolk Southern", US),
        ("CARR", "Carrier Global", US), ("PCAR", "PACCAR Inc.", US),
        ("JCI", "Johnson Controls", US), ("GWW", "W.W. Grainger", US),
        ("URI", "United Rentals", US), ("CPRT", "Copart Inc.", US),
        ("LHX", "L3Harris Technologies", US), ("RSG", "Republic Services", US),
        ("PAYX", "Paychex Inc.", US), ("FAST", "Fastenal Co.", US),
        ("ODFL", "Old Dominion Freight Line", US), ("AME", "AMETEK Inc.", US),
        ("DAL", "Delta Air Lines", US), ("ROK", "Rockwell Automation", US),
        ("UAL", "United Airlines Holdings", US), ("LUV", "Southwest Airlines", US),
    ],
    "Consumer Staples": [
        ("WMT", "Walmart Inc.", US), ("COST", "Costco Wholesale", US),
        ("PG", "Procter & Gamble", US), ("KO", "Coca-Cola Co.", US),
        ("PEP", "PepsiCo Inc.", US), ("PM", "Philip Morris International", US),
        ("UL", "Unilever plc", "United Kingdom"), ("BUD", "Anheuser-Busch InBev", "Belgium"),
        ("MDLZ", "Mondelez International", US), ("MO", "Altria Group", US),
        ("CL", "Colgate-Palmolive", US), ("DEO", "Diageo plc", "United Kingdom"),
        ("TGT", "Target Corp.", US), ("MNST", "Monster Beverage", US),
        ("KMB", "Kimberly-Clark", US), ("KDP", "Keurig Dr Pepper", US),
        ("KR", "Kroger Co.", US), ("SYY", "Sysco Corp.", US),
        ("GIS", "General Mills", US), ("KHC", "Kraft Heinz", US),
        ("HSY", "Hershey Co.", US), ("STZ", "Constellation Brands", US),
        ("ADM", "Archer-Daniels-Midland", US), ("DG", "Dollar General", US),
        ("EL", "Estée Lauder Companies", US), ("CLX", "Clorox Co.", US),
    ],
    "Energy": [
        ("XOM", "Exxon Mobil", US), ("CVX", "Chevron Corp.", US),
        ("SHEL", "Shell plc", "United Kingdom"), ("TTE", "TotalEnergies SE", "France"),
        ("COP", "ConocoPhillips", US), ("ENB", "Enbridge Inc.", "Canada"),
        ("BP", "BP plc", "United Kingdom"), ("EOG", "EOG Resources", US),
        ("WMB", "Williams Companies", US), ("KMI", "Kinder Morgan", US),
        ("SLB", "SLB N.V.", US), ("OKE", "ONEOK Inc.", US),
        ("MPC", "Marathon Petroleum", US), ("PSX", "Phillips 66", US),
        ("SU", "Suncor Energy", "Canada"), ("VLO", "Valero Energy", US),
        ("OXY", "Occidental Petroleum", US), ("TRGP", "Targa Resources", US),
        ("BKR", "Baker Hughes", US), ("FANG", "Diamondback Energy", US),
        ("HAL", "Halliburton Co.", US), ("DVN", "Devon Energy", US),
        ("CTRA", "Coterra Energy", US),
    ],
    "Utilities": [
        ("NEE", "NextEra Energy", US), ("SO", "Southern Co.", US),
        ("CEG", "Constellation Energy", US), ("DUK", "Duke Energy", US),
        ("VST", "Vistra Corp.", US), ("AEP", "American Electric Power", US),
        ("NGG", "National Grid plc", "United Kingdom"), ("SRE", "Sempra", US),
        ("D", "Dominion Energy", US), ("EXC", "Exelon Corp.", US),
        ("XEL", "Xcel Energy", US), ("PEG", "Public Service Enterprise Group", US),
        ("ED", "Consolidated Edison", US), ("PCG", "PG&E Corp.", US),
        ("WEC", "WEC Energy Group", US), ("ETR", "Entergy Corp.", US),
        ("DTE", "DTE Energy", US), ("AEE", "Ameren Corp.", US),
        ("EIX", "Edison International", US), ("AWK", "American Water Works", US),
        ("PPL", "PPL Corp.", US),
    ],
    "Real Estate": [
        ("PLD", "Prologis Inc.", US), ("AMT", "American Tower", US),
        ("WELL", "Welltower Inc.", US), ("EQIX", "Equinix Inc.", US),
        ("SPG", "Simon Property Group", US), ("PSA", "Public Storage", US),
        ("DLR", "Digital Realty Trust", US), ("CBRE", "CBRE Group", US),
        ("CCI", "Crown Castle", US), ("VICI", "VICI Properties", US),
        ("EXR", "Extra Space Storage", US), ("AVB", "AvalonBay Communities", US),
        ("IRM", "Iron Mountain", US), ("EQR", "Equity Residential", US),
        ("VTR", "Ventas Inc.", US), ("CSGP", "CoStar Group", US),
        ("SBAC", "SBA Communications", US), ("WY", "Weyerhaeuser Co.", US),
        ("INVH", "Invitation Homes", US), ("MAA", "Mid-America Apartment Communities", US),
        ("ESS", "Essex Property Trust", US), ("ARE", "Alexandria Real Estate Equities", US),
        ("KIM", "Kimco Realty", US), ("REG", "Regency Centers", US),
        ("UDR", "UDR Inc.", US), ("CPT", "Camden Property Trust", US),
        ("HST", "Host Hotels & Resorts", US), ("BXP", "BXP Inc.", US),
    ],
    "Materials": [
        ("LIN", "Linde plc", US), ("BHP", "BHP Group", "Australia"),
        ("SHW", "Sherwin-Williams", US), ("RIO", "Rio Tinto", "United Kingdom"),
        ("ECL", "Ecolab Inc.", US), ("APD", "Air Products and Chemicals", US),
        ("FCX", "Freeport-McMoRan", US), ("NEM", "Newmont Corp.", US),
        ("SCCO", "Southern Copper", US), ("CTVA", "Corteva Inc.", US),
        ("VALE", "Vale S.A.", "Brazil"), ("NUE", "Nucor Corp.", US),
        ("MLM", "Martin Marietta Materials", US), ("VMC", "Vulcan Materials", US),
        ("PPG", "PPG Industries", US), ("DD", "DuPont de Nemours", US),
        ("DOW", "Dow Inc.", US), ("IFF", "International Flavors & Fragrances", US),
        ("PKG", "Packaging Corp. of America", US), ("STLD", "Steel Dynamics", US),
        ("IP", "International Paper", US), ("BALL", "Ball Corp.", US),
        ("LYB", "LyondellBasell Industries", US), ("CF", "CF Industries", US),
        ("ALB", "Albemarle Corp.", US), ("MOS", "Mosaic Co.", US),
    ],
}

REAL_COUNTRY: dict[str, str] = {t: c for xs in REAL_STOCKS.values() for t, _, c in xs}

# Real tickers that are also everyday words: the chat assistant ignores them in lowercase text
WORD_TICKERS = {"now", "low", "all", "are", "on", "key", "cat", "so", "ed", "de", "mo", "ma",
                "ph", "well", "ball", "el", "ip", "met", "mar", "dash", "see", "it", "ge", "hd",
                "cf", "dd", "bk", "su", "se", "bp", "ko", "pg", "gs", "ms", "ice", "ci", "ups",
                "ba", "has", "mos", "wm", "gm", "hon", "dow", "pm", "cl", "tt", "ul", "re", "air"}


def assign(sectors: list[str], market_cap: list[float]) -> list[tuple[str, str, str, str]]:
    """Real (ticker, name, country, sector) for every stock slot — never a made-up name.

    The biggest simulated stock in each sector gets that sector's first (largest) real company.
    If a sector has more slots than real names, its smallest extra slots take the largest unused
    companies from other sectors and switch to that company's sector."""
    n = len(sectors)
    total = sum(len(x) for x in REAL_STOCKS.values())
    if n > total:
        raise ValueError(f"universe of {n} stocks exceeds the {total} real companies listed")
    out: list[tuple[str, str, str, str] | None] = [None] * n
    by_sector: dict[str, list[int]] = {}
    for i, s in enumerate(sectors):
        by_sector.setdefault(s, []).append(i)
    used: set[str] = set()
    overflow: list[int] = []
    for s, idx in by_sector.items():
        names = REAL_STOCKS.get(s, [])
        for k, i in enumerate(sorted(idx, key=lambda j: -market_cap[j])):
            if k < len(names):
                t, nm, c = names[k]
                out[i] = (t, nm, c, s)
                used.add(t)
            else:
                overflow.append(i)
    spare = [(t, nm, c, s) for s, xs in REAL_STOCKS.items() for t, nm, c in xs if t not in used]
    # interleave sectors so the spares stay a mix, largest companies first
    spare.sort(key=lambda x: [y[0] for y in REAL_STOCKS[x[3]]].index(x[0]))
    for i, x in zip(sorted(overflow, key=lambda j: -market_cap[j]), spare, strict=False):
        out[i] = x
    return [x for x in out if x is not None] if all(out) else _missing()


def _missing() -> list[tuple[str, str, str, str]]:
    raise ValueError("could not give every stock a real company name")
