# OpenMeridian

<p align="center">
  <img src="openmeridian/resources/openmeridian-256.png" alt="OpenMeridian logo" width="160">
</p>

**Free and open-source lightweight ERP for small engineering businesses.** Items, bills of materials, stock, sales,
invoices, purchasing, work orders and planning in one file on your computer, connected to the controlled documents in
[RevisionWorx](https://github.com/nrobertson152/RevisionWorx). Windows and Linux. Version 0.1.0.

Copyright © 2026 Nate Robertson.
Licensed under the GNU General Public License v3.0 or later (see `LICENSE`).

OpenMeridian works fully offline and has no accounts, telemetry, advertisements or feature limits. If you find it useful
you can optionally [support development on Ko-fi](https://ko-fi.com/nr270343).

![OpenMeridian's work orders, with a contextual panel](docs/images/screenshot.png)

## What it does

- **Items and BOMs.** Bought and made items, multi-level BOMs with a rolled-up cost, and refused cycles.
- **Stock you can trust.** Every movement is a permanent ledger entry. On-hand is always the sum of the ledger, and
  corrections are new entries with a reason. Costs are moving averages.
- **Sales to cash.** Sales orders, partial shipments, invoices for what actually shipped, tax kept with the invoice,
  PDFs and CSV exports.
- **Purchasing.** Purchase orders, partial receipts, what's late.
- **Production.** Work orders that reserve parts, consume them on completion and show what's short.
- **Planning.** What to buy and make to cover demand and reorder points, through every BOM level. You review the
  suggestions, and they become draft orders.
- **Find anything.** Ctrl+K searches every record. Every list has filters and a panel for what you've selected, with
  one clear next step.

![The same window on the Graphite theme](docs/images/screenshot-graphite.png)

Try it without entering anything: choose **Explore a sample company** on the start page.

## With RevisionWorx

Point a company at a RevisionWorx workspace in **Settings**. RevisionWorx stays the record for engineering, and
OpenMeridian only ever reads it, through RevisionWorx's own command line.

- **Link items** to their controlled documents and see what's released.
- **Import a BOM from a released revision**, read by RevisionWorx's own BOM reader. Stock, costs and prices stay as they
  are. A revision that isn't released is refused unless you choose to import it anyway.
- **Work orders record the revision they build**, at the moment they're released.
- **Out of step:** when engineering releases a new revision, the Overview, the sidebar and the item say which BOMs and
  work orders were made from an older one. Nothing changes until someone imports the new one.
- **Open engineering changes** are shown beside the documents.

## What it doesn't do

OpenMeridian is deliberately small, and a simple result mustn't look like an exact one.

- **It isn't an accounting system.** No general ledger, payments in part, credit notes, multi-currency or tax returns,
  and one tax rate. Have your accountant check anything you rely on.
- **Planning is not scheduling.** It ignores capacity and dates of individual demands. The "earliest" date is today plus
  that item's own lead time, without adding the levels below it.
- **One location and no lots or serial numbers.** Bins are a note on the item.
- **One person at a time.** A company file on your own disk is the supported setup. Using one over a network share has
  **not** been tested, and SQLite's locking can't be relied on over network filesystems.
- **The logo is placeholder artwork.**

## Install from source

```sh
python -m pip install "openmeridian[gui] @ git+https://github.com/nrobertson152/OpenMeridian"
openmeridian
```

Python 3.10–3.13 and SQLite 3.37 or newer. The core and command line use only the standard library; the window uses
PySide6 (Qt 6, LGPL-3.0). RevisionWorx is optional, and OpenMeridian finds it on your PATH, as a Python package next to
it, or at the location you give in Settings.

There are no packaged binaries yet.

## Development

See `AGENTS.md` for the rules and commands, `docs/COMPANY_FILE.md` for the file format and `CHANGELOG.md` for changes.
