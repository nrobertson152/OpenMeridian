# OpenMeridian — development workflow

OpenMeridian follows the same rules as OpenSchematix and RevisionWorx.

## Roles

- **Director (`nrobertson152`)** has sole authority over releases, release/version tags and licensing.
- **Developer (Claude)** plans, implements, tests and reviews its own work on branches and PRs.

## Product rules

- GPL-3.0-or-later, free and open source.
- Fully offline: no network access, accounts, telemetry, ads or feature limits.
- The core (everything outside `openmeridian/gui`) uses the standard library only. The window uses PySide6.
  `[dev]` extras are for tests and builds only.
- Windows and Linux; Python 3.10–3.13; PySide6 6.5 or newer.
- RevisionWorx is the record for engineering. OpenMeridian only reads it, through its command line, and never writes to
  a workspace. It fails closed: an unreleased revision isn't imported unless the user chooses that.
- `.meridian` files must keep opening. Document any format change in `docs/COMPANY_FILE.md`, version it and test it.
- Money is integer cents and quantities integer thousandths. No floats in stored values.
- The stock ledger and activity log are append-only, enforced in the file. Every change is one transaction.
- A malformed file shows a message; it never crashes.
- Say what the program doesn't do. It isn't an accounting system and doesn't claim to be.
- Interface: same tokens, themes and icon language as OpenSchematix; RevisionWorx's status-block sentence and one
  primary action. No new colours or styles outside `gui/theme.py`.

## Priorities

1. Data loss, corruption and unsafe writes.
2. Wrong behaviour: stock, money, what was built from which revision.
3. Crashes and runaway resource use.
4. Platform compatibility.
5. Performance, features, cosmetics.

## Commands

```sh
python -m pip install -e ".[dev]"            # Linux also: sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0
python -m compileall -q openmeridian tests
QT_QPA_PLATFORM=offscreen python -m pytest -q -ra
python -m openmeridian --self-test
```

The RevisionWorx tests run against the real program when it can be imported and skip otherwise; CI installs it.

Add a regression test with every behaviour change. Never weaken or skip tests to make CI pass. Never describe
unverified behaviour (native Windows, network shares) as verified.
