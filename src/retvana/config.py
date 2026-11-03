"""Plan configuration: every input the model needs, with generic defaults, and
example_plan(), a synthetic two-person household. Plans round-trip to JSON for
save/load/sharing."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Optional


@dataclass
class Person:
    key: str                      # 'P1' or 'P2'
    name: str
    birth_year: int
    cpp_monthly_at_65: float      # Service Canada estimate, in year-turning-65 dollars
    cpp_start_age: int = 65       # 60-70
    oas_start_age: int = 65       # 65-70
    taxable_share: float = 0.75   # share of non-registered return that is taxable
    rrif_min_age: int = 55        # earliest RRIF/LIF start (LIRA unlock)
    death_age: int = 95           # alive through the end of the year this age is reached


ACCOUNT_KINDS = ('registered', 'tfsa', 'nonreg')   # accepted values of Account.kind


def check_account_kind(account: 'Account') -> None:
    """Raise ValueError naming the account and the kind when the kind is not in ACCOUNT_KINDS."""
    if account.kind not in ACCOUNT_KINDS:
        raise ValueError(f'account {account.name!r} has unknown kind {account.kind!r}; '
                         f'expected one of {", ".join(ACCOUNT_KINDS)}')


@dataclass
class Account:
    name: str
    owner: str                    # 'P1' or 'P2'
    kind: str                     # one of ACCOUNT_KINDS: 'registered', 'tfsa' or 'nonreg'
    balance: float                # value at current_year
    return_rate: float            # growth until retirement
    contribution: float = 0.0     # yearly contribution until retirement
    contribution_is_tfsa_limit: bool = False
    volatility: float = 0.12      # yearly volatility until retirement (Monte Carlo)


@dataclass
class ConsultingIncome:
    """Self-employed income in retirement (net of business expenses, before tax)."""
    owner: str                    # 'P1' or 'P2'
    annual: float                 # per year, today's dollars
    start_year: int
    end_year: int                 # last year of income (inclusive)
    indexed: bool = True          # rises with inflation
    rrsp: bool = True             # contribute the new RRSP room (18% of last year's income) each year
    label: str = 'Consulting'
    via_corp: bool = False        # earned through the consulting corporation (paid out as dividends)


@dataclass
class OptionGrant:
    grant_date: str
    expiry: str
    grant_price: float
    granted: int
    available: int


@dataclass
class Mortgage:
    name: str
    secured_on: str
    balance: float                # balance at start of current term
    rate: float
    amort_years: float            # amortization remaining at term start
    first_payment_year: int
    first_payment_month: int
    term_months: int
    renewal_rate: Optional[float] = None   # None = same as current rate


@dataclass
class Property:
    name: str
    segment: str
    value_today: float
    peak_value: float             # 2022 peak (or purchase price where bought at peak)
    purchase_price: float
    purchase_year: int
    principal_residence: bool     # True = sold tax-free under the PRE
    acb: Optional[float] = None   # None = purchase price
    description: str = ''


@dataclass
class Townhouse:
    price_today: float = 1_000_000
    peak_value: float = 1_100_000
    segment: str = 'freehold_townhouse'
    follows_market: bool = True
    areas: str = ''


@dataclass
class Segment:
    """Recovery model for one property type (see property_model.py)."""
    key: str
    label: str
    recovery_target: float        # long-run fair value as a share of the 2022 peak
    recovery_speed: float         # share of the gap to fair value closed per year
    long_run_growth: float        # fair-value growth per year
    beta: float                   # sensitivity to the shared market shock
    idio_vol: float               # property-specific yearly volatility
    sale_discount: float = 0.0    # liquidity haircut when selling
    rationale: str = ''


@dataclass
class LegacyScenario:
    name: str
    recovery_years: int
    recovery_rate: float
    long_run_rate: float
    rationale: str = ''


@dataclass
class ExpenseItem:
    name: str
    monthly: float                         # go-go years
    discretionary: bool = False
    monthly_later: Optional[float] = None  # None = same as go-go


LEGACY_NONREG_KEY = 'base_nonreg_p2'   # plans saved before nonreg-accounts; converted by Plan.from_dict


def _legacy_nonreg_account(plan: 'Plan', balance: float) -> 'Account':
    """The Equivalent_Account for a saved base_nonreg_p2 (nonreg-accounts Requirement 5)."""
    p2 = next((p for p in plan.people if p.key == 'P2'), None)
    stem = f'{p2.name} non-registered' if p2 is not None and p2.name else 'Person 2 non-registered'
    taken = {a.name for a in plan.accounts}
    name, k = stem, 2
    while name in taken:
        name, k = f'{stem} ({k})', k + 1
    return Account(name, 'P2', 'nonreg', balance, 0.0, 0.0, False, 0.0)


@dataclass
class Plan:
    # --- timeline ---
    start_year: int = 2032
    current_year: int = 2026
    end_year: int = 2080          # derived: second death, or fixed_end_year (see sync_end_year)
    fixed_end_year: int = 2080    # used when death ages are off
    # --- economics ---
    return_rate: float = 0.055
    inflation: float = 0.028
    expense_cpi: float = 0.028
    gogo_years: int = 15
    # --- household ---
    people: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    expenses: list = field(default_factory=list)
    income_splitting: bool = False
    tfsa_limit: float = 7000
    # --- employee stock options (Person 1) ---
    options_share_price: float = 0.0
    options_marginal_rate: float = 0.5353
    option_grants: list = field(default_factory=list)
    # --- property ---
    property_mode: str = 'legacy'          # 'legacy' (Bear/Base/Bull/Boom) or 'recovery'
    legacy_scenario: str = 'Base'
    legacy_scenarios: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    market_vol: float = 0.07               # shared yearly market shock (rates, sentiment)
    market_momentum: float = 0.5           # autocorrelation of market shocks
    properties: list = field(default_factory=list)
    mortgages: list = field(default_factory=list)
    townhouse: Townhouse = field(default_factory=Townhouse)
    commission_rate: float = 0.05
    hst: float = 0.13
    cg_inclusion: float = 0.5
    ltt_brackets: list = field(default_factory=lambda: [
        [0, 55_000, 0.005, 0.005], [55_000, 250_000, 0.01, 0.01],
        [250_000, 400_000, 0.015, 0.015], [400_000, 2_000_000, 0.02, 0.02],
        [2_000_000, 3_000_000, 0.025, 0.025]])
    # --- tax (2026 combined federal + Ontario) ---
    tax_thresholds: list = field(default_factory=lambda: [
        0, 62414, 67778, 105180, 124830, 135555, 181980, 210130, 266905])
    tax_rates: list = field(default_factory=lambda: [
        0.2005, 0.2415, 0.2965, 0.3148, 0.3389, 0.3791, 0.4341, 0.4641, 0.5353])
    bpa: float = 19053
    index_brackets_to_start: bool = True
    rrif_factors: dict = field(default_factory=dict)
    # --- life expectancy and survivor ---
    # use_death_ages: the projection ends at the second death (end_year is set from the ages),
    # and after the first death the survivor rules apply: deceased's CPP/OAS stop, CPP survivor
    # benefit, everything rolls over to the survivor tax-free, no income splitting, lower spending.
    use_death_ages: bool = False
    survivor_spending: float = 0.70        # survivor's spending as a share of the couple's
    cpp_max_monthly_2026: float = 1507.65  # maximum CPP retirement pension at 65, Jan 2026
    cpp_survivor_rate: float = 0.60        # survivor 65+: 60% of the deceased's pension
    cpp_survivor_rate_under65: float = 0.375
    # --- registered withdrawal strategy ---
    # 'minimums': RRIF from retirement, take the prescribed minimum (the original spreadsheet's behaviour)
    # 'defer':    keep RRSPs until 71 (first RRIF minimum at 72); draw only when other money runs out
    # 'bracket':  as 'defer', but each year draw enough to bring taxable income up to a target
    #             (today's dollars, indexed) until fill_until_age, then minimums
    withdrawal_strategy: str = 'minimums'
    bracket_target: float = 95_000         # per person, today's dollars
    fill_until_age: int = 71
    rrif_conversion_age: int = 71          # 'defer' / 'bracket': RRIF by end of this year, minimums after
    tfsa_topup: bool = False               # put surpluses into TFSA room before non-registered
    accurate_extra_tax: bool = False       # tax extra withdrawals at the actual marginal rate, not the top rate
    # --- consulting income (self-employed, in retirement) ---
    consulting: list = field(default_factory=list)
    ympe_2026: float = 74_600              # CPP year's maximum pensionable earnings
    yampe_2026: float = 85_000             # CPP2 ceiling
    cpp_exemption: float = 3_500           # basic exemption (not indexed)
    cpp_se_rate: float = 0.119             # self-employed base + first additional (both halves)
    cpp2_se_rate: float = 0.08             # self-employed CPP2 (both halves)
    rrsp_limit_2026: float = 33_810
    # --- consulting corporation (CCPC, Ontario) ---
    # Contracts with via_corp=True are earned inside the corporation: small-business tax, then the
    # after-tax profit is invested in the corporation and paid out as non-eligible dividends.
    corp_balance: float = 0.0              # corporate investments today (dormant: 0)
    corp_sbd_rate: float = 0.112           # federal 9% + Ontario 2.2% (from July 2026)
    corp_general_rate: float = 0.265       # active income above the (ground-down) small-business limit
    corp_sbd_limit: float = 500_000
    corp_passive_rate: float = 0.5017      # Ontario CCPC investment income
    corp_refundable_rate: float = 0.3067   # added to non-eligible RDTOH
    corp_refund_rate: float = 0.3833       # dividend refund per dollar of taxable dividend
    ne_gross_up: float = 0.15              # non-eligible dividend gross-up
    ne_dtc_rate: float = 0.110201          # federal 9.0301% + Ontario 1.99% of the grossed-up dividend
    dividend_policy: str = 'target'        # 'target': fill each shareholder's taxable income; 'all': pay all out
    dividend_target: float = 90_000        # taxable income per shareholder, today's dollars
    p1_shareholder: bool = False           # Person 1 holds shares (TOSI rules decide when they can be paid)
    # --- sustainable spending solver ---
    spend_target_estate: float = 1_000_000  # estate after tax to leave, today's dollars
    spend_mode: str = 'all'                 # 'all' items or 'discretionary' only
    spend_confidence: float = 0.90          # with market risk on
    # --- investment-return Monte Carlo ---
    returns_mc: bool = False               # vary yearly returns (sequence-of-returns risk)
    return_vol: float = 0.10               # yearly volatility of the retirement portfolio
    mc_pre_retirement: bool = True         # also vary account growth until retirement
    first_year_shock: float = 0.0          # stress test: added to the first retirement-year return
    success_floor: float = 0.0             # "success" = capital stays above this through end_year
    # --- CPP / OAS ---
    cpp_inflation: float = 0.028
    cpp_full_years: int = 39
    cpp_proportional: bool = True
    oas_base_year: int = 2026
    oas_max_monthly: float = 751.97
    oas_threshold: float = 95323
    oas_uplift_75: float = 0.10
    oas_clawback_rate: float = 0.15

    # ---------- helpers ----------
    def person(self, key: str) -> Person:
        return next(p for p in self.people if p.key == key)

    def segment(self, key: str) -> Segment:
        return next(s for s in self.segments if s.key == key)

    def death_year(self, key: str) -> int:
        """Last year the person is alive (dies at the end of it); far future when ages are off."""
        p = self.person(key)
        return p.birth_year + p.death_age if self.use_death_ages else 9999

    def second_death_year(self) -> int:
        return max(self.death_year('P1'), self.death_year('P2'))

    def sync_end_year(self) -> None:
        """The plan ends at the second death with death ages on, else at fixed_end_year."""
        self.end_year = self.second_death_year() if self.use_death_ages else self.fixed_end_year

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> 'Plan':
        types = {'people': Person, 'accounts': Account, 'expenses': ExpenseItem, 'consulting': ConsultingIncome,
                 'option_grants': OptionGrant, 'legacy_scenarios': LegacyScenario,
                 'segments': Segment, 'properties': Property, 'mortgages': Mortgage}
        kw = {}
        names = {f.name for f in fields(cls)}
        for k, v in d.items():
            if k not in names:
                continue
            if k in types:
                kw[k] = [types[k](**x) for x in v]
            elif k == 'townhouse':
                kw[k] = Townhouse(**v)
            elif k == 'rrif_factors':
                kw[k] = {int(a): float(b) for a, b in v.items()}
            else:
                kw[k] = v
        plan = cls(**kw)
        legacy = d.get(LEGACY_NONREG_KEY)
        if legacy is not None and float(legacy) != 0:
            plan.accounts.append(_legacy_nonreg_account(plan, float(legacy)))
        return plan

    @classmethod
    def from_json(cls, text: str) -> 'Plan':
        return cls.from_dict(json.loads(text))

    def copy(self) -> 'Plan':
        return Plan.from_dict(self.to_dict())


RRIF_FACTORS = {0: 0.0, **{55 + i: f for i, f in enumerate([
    0.0286, 0.0294, 0.0303, 0.0313, 0.0323, 0.0333, 0.0345, 0.0357, 0.037, 0.0385, 0.04,
    0.0417, 0.0435, 0.0455, 0.0476, 0.05, 0.0738, 0.0748, 0.0759, 0.0771, 0.0785, 0.0799,
    0.0815, 0.0833, 0.0853, 0.0875, 0.0899, 0.0927, 0.0958, 0.0993, 0.1033, 0.1079, 0.1133,
    0.1196, 0.1271, 0.1362, 0.1473, 0.1612, 0.1792, 0.2, 0.2])}}




def example_plan() -> Plan:
    """A synthetic two-person household with round values, made up for this repository.

    It reaches every feature path of the model somewhere in the regression cases: both RRIF
    start rules, the LIRA unlock (Person 2 is 52 at a 2032 retirement and reaches 55 in 2035),
    the survivor rules, OAS clawback, a negative property surplus (Bear) and a positive one
    (Bull with a fixed townhouse price), and extra registered and TFSA draws in the cascade.
    The model switches stay at their defaults (as in the original spreadsheet); the App's
    fresh_plan() turns on the realism settings."""
    p = Plan()
    p.current_year = 2026
    p.start_year = 2032
    p.rrif_factors = dict(RRIF_FACTORS)
    p.people = [
        Person('P1', 'Alex', 1975, 1100, death_age=92),
        Person('P2', 'Sam', 1980, 1300, death_age=96),
    ]
    p.accounts = [
        Account('Alex RRSP', 'P1', 'registered', 600_000, 0.06, 6_000),
        Account('Alex LIRA', 'P1', 'registered', 50_000, 0.06, 0),
        Account('Alex TFSA', 'P1', 'tfsa', 120_000, 0.04, 0, True, 0.06),
        Account('Sam RRSP', 'P2', 'registered', 300_000, 0.06, 0),
        Account('Sam LIRA', 'P2', 'registered', 400_000, 0.06, 0),
        Account('Sam DC pension', 'P2', 'registered', 150_000, 0.06, 18_000),
        Account('Sam TFSA', 'P2', 'tfsa', 120_000, 0.04, 0, True, 0.06),
        Account('Sam non-registered', 'P2', 'nonreg', 150_000, 0.0, 0, False, 0.0),
    ]
    p.expenses = [
        ExpenseItem('Property tax', 500),
        ExpenseItem('Utilities', 250),
        ExpenseItem('Home maintenance', 300),
        ExpenseItem('Home insurance', 150),
        ExpenseItem('Health insurance', 400),
        ExpenseItem('Internet and phones', 200),
        ExpenseItem('Groceries', 1_000),
        ExpenseItem('Car and transit', 400),
        ExpenseItem('Clothing and personal', 250),
        ExpenseItem('Travel', 3_000, True, 1_500),
        ExpenseItem('Restaurants', 1_000, True, 600),
        ExpenseItem('Hobbies', 500, True, 300),
    ]
    # employee stock options (Person 1), all expiring after retirement
    p.options_share_price = 4.0
    p.option_grants = [
        OptionGrant('2023-03-01', '2033-03-01', 1.0, 10_000, 10_000),
        OptionGrant('2024-03-01', '2034-03-01', 2.0, 10_000, 10_000),
        OptionGrant('2025-03-01', '2035-03-01', 3.0, 5_000, 5_000),
    ]
    p.legacy_scenarios = [
        LegacyScenario('Bear', 3, 0.0, 0.025, 'Slump persists: flat for 3 years, then roughly inflation.'),
        LegacyScenario('Base', 3, 0.06, 0.035, 'Gradual recovery as inventory clears, then inflation + ~0.7%.'),
        LegacyScenario('Bull', 3, 0.10, 0.045, 'Sharp rebound for 3 years, then strong long-run growth.'),
        LegacyScenario('Boom', 99, 0.115, 0.115, '2012-2022 rates (10-13%) sustained. Stress test, not a plan.'),
    ]
    p.segments = [
        Segment('condo_townhouse', 'Condo townhouse (family size)', 1.00, 0.30, 0.035, 0.9, 0.05, 0.0,
                'Scarce, family-sized, end-user demand. Fell far less than condo apartments; '
                'expect full recovery to the 2022 peak.'),
        Segment('condo_apartment', 'Condo apartment (1-2 bed)', 0.90, 0.20, 0.030, 1.1, 0.07, 0.0,
                'Recovers most, not all, of the loss as new supply is absorbed.'),
        Segment('studio', 'Studio / micro unit', 0.85, 0.15, 0.025, 1.2, 0.09, 0.03,
                'Investor-driven, hardest hit, most supply in the pipeline, hard to finance. '
                'Slow, partial recovery and a 3% haircut for a thinner buyer pool.'),
        Segment('freehold_townhouse', 'Freehold townhouse', 1.00, 0.30, 0.040, 1.0, 0.05, 0.0,
                'Land-backed, end-user demand. Fell less than condos and has historically '
                'outgrown them; this is the price you are buying into.'),
    ]
    p.properties = [
        Property('Property 1', 'condo_townhouse', 750_000, 850_000, 800_000, 2020, True, None),
        Property('Property 2', 'studio', 350_000, 420_000, 400_000, 2019, False, 380_000),
        Property('Property 3', 'condo_apartment', 500_000, 650_000, 650_000, 2021, False, None),
    ]
    p.mortgages = [
        Mortgage('Mortgage on Property 3', 'Property 3', 450_000, 0.045, 25, 2025, 2, 36),
        Mortgage('Mortgage on Property 1', 'Property 1', 180_000, 0.04, 15, 2025, 11, 36),
    ]
    p.townhouse = Townhouse(price_today=1_050_000, peak_value=1_150_000, follows_market=True)
    return p
