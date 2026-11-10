"""Deterministic generator for extra demo households (scales the demo book to ~100 clients).

Used once, when the book file (data/book/book.json) is first created; after that the book file
is the source of truth and nothing here runs again unless the book is regenerated on purpose.
"""

from __future__ import annotations

import numpy as np

from app.db.seed_specs import AccountSpec, ClientSpec
from app.domain.entities import AccountType, TaxProfile

AT = AccountType

FIRST = [
    "Amelia",
    "Benjamin",
    "Clara",
    "Daniel",
    "Elena",
    "Felix",
    "Grace",
    "Henry",
    "Isla",
    "Jonah",
    "Katherine",
    "Liam",
    "Maya",
    "Nathan",
    "Olivia",
    "Peter",
    "Quinn",
    "Rosa",
    "Samuel",
    "Tara",
    "Victor",
    "Wendy",
    "Xavier",
    "Yara",
    "Zachary",
    "Aisha",
    "Bruno",
    "Celeste",
    "Dmitri",
    "Esme",
    "Farah",
    "Gabriel",
    "Hana",
    "Ivan",
    "Jasmine",
    "Kofi",
    "Leona",
    "Mateo",
    "Nadia",
    "Omar",
]
LAST = [
    "Albright",
    "Bancroft",
    "Calloway",
    "Delacroix",
    "Ellison",
    "Fairbanks",
    "Galloway",
    "Hartwell",
    "Ingram",
    "Jansen",
    "Kessler",
    "Langford",
    "Montague",
    "Northcott",
    "Oyelaran",
    "Prescott",
    "Quintero",
    "Ramsay",
    "Sandoval",
    "Thorne",
    "Underwood",
    "Valdivia",
    "Wexford",
    "Yamamoto",
    "Zielinski",
    "Ashby",
    "Brightwater",
    "Castellano",
    "Dunmore",
    "Eastwood",
    "Fitzgerald",
    "Greenhalgh",
    "Holloway",
    "Iverson",
    "Kowalski",
    "Lindgren",
    "Marchetti",
    "Nakamura",
    "Osei",
    "Pacheco",
    "Rourke",
    "Sato",
    "Tremblay",
    "Vasquez",
    "Whitmore",
    "Abiodun",
    "Bergstrom",
    "Chatterjee",
    "Duarte",
    "Engstrom",
    "Ferraro",
    "Gupta",
    "Haddad",
    "Ivanova",
    "Jorgensen",
    "Kapoor",
    "Lombardi",
    "Mbeki",
    "Novak",
    "Okonkwo",
]
STATES = [  # (state, top marginal state rate)
    ("CA", 0.133),
    ("NY", 0.109),
    ("TX", 0.0),
    ("FL", 0.0),
    ("MA", 0.05),
    ("IL", 0.0495),
    ("WA", 0.0),
    ("NJ", 0.1075),
    ("CO", 0.044),
    ("GA", 0.0549),
    ("NC", 0.045),
    ("VA", 0.0575),
    ("PA", 0.0307),
    ("AZ", 0.025),
    ("MN", 0.0985),
    ("OR", 0.099),
    ("CT", 0.0699),
    ("MD", 0.0575),
]
FEDERAL = [(0.37, 0.238), (0.35, 0.238), (0.32, 0.15), (0.24, 0.15)]
CUSTODIANS = ["Schwab", "Fidelity", "Pershing"]
NOTES = [
    "Prefers low turnover.",
    "Quarterly review; tax-sensitive.",
    "Charitable giving planned next year.",
    "Business owner; irregular cash flows.",
    "Retired; income focus.",
    "Saving for a second home.",
    "Concentrated position from former employer.",
    "Wants consolidated household reporting.",
    "Estate planning in progress.",
    "Comfortable with active risk.",
]


def generate_clients(
    seed: int, n: int, total_aum: float, phone_start: int = 110, taken: set[str] | None = None
) -> list[ClientSpec]:
    """``n`` households whose account market values sum to ``total_aum`` (before cash drift).

    Every generated household is already managed (has a target model and 1–3 years of history),
    so the onboarding household of the hand-written book stays the only one without a model.
    """
    rng = np.random.default_rng([seed, 9_100])
    sizes = np.clip(rng.lognormal(mean=np.log(9e6), sigma=0.95, size=n), 6e5, 1.5e8)
    sizes *= total_aum / sizes.sum()
    names: set[str] = set(taken or ())
    out: list[ClientSpec] = []
    for i in range(n):
        kind = str(
            rng.choice(["individual", "couple", "family", "trust"], p=[0.4, 0.3, 0.15, 0.15])
        )
        for _ in range(200):  # redraw until the name is new
            last = str(rng.choice(LAST))
            first, second = (str(x) for x in rng.choice(FIRST, size=2, replace=False))
            name = {
                "individual": f"{first} {last}",
                "couple": f"{first} & {second} {last}",
                "family": f"{last} Family",
                "trust": f"{last} {'Family' if rng.random() < 0.5 else 'Revocable'} Trust",
            }[kind]
            if name not in names:
                break
        else:
            raise ValueError("ran out of unique client names")
        names.add(name)
        state, state_rate = STATES[int(rng.integers(len(STATES)))]
        fed_st, fed_lt = FEDERAL[int(rng.choice(4, p=[0.45, 0.25, 0.2, 0.1]))]
        years = round(float(rng.uniform(1.0, 3.0)), 1)
        custodian = str(rng.choice(CUSTODIANS))
        main = {
            "individual": (AT.INDIVIDUAL_TAXABLE, "Individual"),
            "couple": (AT.JOINT_TAXABLE, "Joint brokerage"),
            "family": (AT.JOINT_TAXABLE, "Family joint"),
            "trust": (AT.TRUST, "Trust"),
        }[kind]
        extra_pool = [(AT.IRA, "Rollover IRA"), (AT.ROTH_IRA, "Roth IRA"), (AT.TRUST, "Trust")]
        n_extra = int(rng.choice([0, 1, 2], p=[0.35, 0.45, 0.2]))
        picks = [extra_pool[j] for j in rng.choice(3, size=n_extra, replace=False)]
        kinds = [main, *picks]
        shares = rng.dirichlet([4.0] + [1.5] * n_extra)
        accounts = []
        for (atype, nick), share in zip(kinds, shares, strict=True):
            target = "TR" if rng.random() < 0.7 else "INC"
            prev = (
                ("INC" if target == "TR" else "TR") if years > 1.5 and rng.random() < 0.06 else None
            )
            accounts.append(
                AccountSpec(
                    atype,
                    custodian,
                    nick,
                    target,
                    round(float(sizes[i] * share), -3),
                    years,
                    locked_legacy=bool(atype.is_taxable and rng.random() < 0.1),
                    previous_model_id=prev,
                )
            )
        slug = name.lower().replace("&", "and").replace("(", "").replace(")", "")
        slug = ".".join(slug.split())
        out.append(
            ClientSpec(
                name,
                kind,
                f"{slug}@example.com",
                f"555-{phone_start + i:04d}",
                TaxProfile(fed_st, fed_lt, state, state_rate),
                str(rng.choice(NOTES)),
                accounts,
            )
        )
    return out
