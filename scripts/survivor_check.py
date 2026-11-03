"""Check the survivor rules around the first death (independent of the vector check, which only
proves the two engines agree).

  .venv/bin/python scripts/survivor_check.py
"""
import sys


from retvana.config import example_plan          # noqa: E402
from retvana.engine import project, summary      # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(f'{"PASS" if cond else "FAIL"}  {label}{"  " + detail if detail else ""}')


for first, death_age_p1, death_age_p2 in (('P1', 80, 94), ('P2', 97, 70)):
    p = example_plan()
    p.property_mode, p.use_death_ages, p.income_splitting = 'recovery', True, True
    p.tfsa_topup = p.accurate_extra_tax = True
    p.person('P1').death_age, p.person('P2').death_age = death_age_p1, death_age_p2
    df, st = project(p)
    d1 = min(p.death_year('P1'), p.death_year('P2'))
    d2 = p.second_death_year()
    dead, surv = (('F', 'I', 'BU', 'CC', 'CD', 'R'), ('S', 'V', 'BX', 'CJ', 'CK', 'AE')) if first == 'P1' \
        else (('S', 'V', 'BX', 'CJ', 'CK', 'AE'), ('F', 'I', 'BU', 'CC', 'CD', 'R'))
    before, after = df.loc[d1], df.loc[d1 + 1]
    print(f'\n--- {first} dies first: end of {d1} (P1 {death_age_p1}, P2 {death_age_p2}); plan ends {d2} ---')
    check('plan ends at the second death', p.end_year == d2 and df['A'].iloc[-1] == d2, f'end_year={p.end_year}')
    check('deceased balances are zero after death',
          all(abs(df.loc[d1 + 1:, c]).max() < 1e-6 for c in dead[:3]))
    check("deceased's CPP, OAS and tax stop", all(abs(df.loc[d1 + 1:, c]).max() < 1e-6 for c in dead[3:]))
    # rollover conserves money: survivor's opening balances = both balances carried forward
    carried = {}
    for tag, (bal, ret, out) in {'nonreg': (('F', 'S'), ('G', 'T'), ('H', 'U')),
                                 'tfsa': (('BU', 'BX'), ('BV', 'BY'), ('BW', 'BZ'))}.items():
        nxt = sum(max(before[b] + (before[r] if tag == 'tfsa' else 0) - before[o]
                      + (before['T_P1' if b == 'BU' else 'T_P2'] if tag == 'tfsa' else 0), 0)
                  for b, r, o in zip(bal, ret, out))
        got = after[bal[1] if first == 'P1' else bal[0]]
        check(f'{tag} rolls over in full', abs(got - nxt) < 0.01, f'${got:,.0f} vs ${nxt:,.0f}')
    exp_ratio = after['B'] / (before['B'] * (1 + p.inflation))
    check('survivor spending drops to 70%', abs(exp_ratio - p.survivor_spending) < 1e-9, f'{exp_ratio:.3f}')
    own = surv[3]
    check('survivor CPP includes the survivor benefit (or is at the cap)', after[own] >= before[own] * (1 + p.cpp_inflation) - 1e-6,
          f'${before[own]:,.0f} -> ${after[own]:,.0f}')
    check('no income splitting after the first death',
          all(abs(df.loc[d1 + 1:, 'BR'] - df.loc[d1 + 1:, 'BD']) < 1e-6) and
          all(abs(df.loc[d1 + 1:, 'BS'] - df.loc[d1 + 1:, 'BH']) < 1e-6))
    s = summary(p, df, st)
    print(f'      estate after tax at {d2}: ${s["Estate after tax"]:,.0f}; tax before/after first death: '
          f'${before["R"] + before["AE"]:,.0f} -> ${after["R"] + after["AE"]:,.0f}')

# survivor CPP formula on a case below the cap
p = example_plan()
p.use_death_ages = True
p1, p2 = p.person('P1'), p.person('P2')
p1.cpp_monthly_at_65, p2.cpp_monthly_at_65 = 600, 2000
p1.death_age, p2.death_age = 97, 75
df, _ = project(p)
y = p.death_year('P2') + 1
cap = p.cpp_max_monthly_2026 * 12 * (1 + p.cpp_inflation) ** (y - 2026)
own = (600 * 12 * (1 + p.cpp_inflation) ** (y - (p1.birth_year + 65))
       * min(1, (p.start_year - (p1.birth_year + 18)) / 39))
contrib = min(1, (p.start_year - (p2.birth_year + 18)) / 39)
dec = 2000 * 12 * (1 + p.cpp_inflation) ** (y - (p2.birth_year + 65)) * contrib
expect = min(own + 0.6 * dec, cap)
check('survivor CPP = own + 60% of deceased, capped at the maximum', abs(df.loc[y, 'CC'] - expect) < 0.01,
      f'${df.loc[y, "CC"]:,.0f} (own ${own:,.0f} + 60% x ${dec:,.0f}, cap ${cap:,.0f})')

print('\nSURVIVOR CHECK', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
