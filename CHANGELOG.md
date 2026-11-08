# Changelog

## Unreleased

First version: company files, items and BOMs, stock ledger, sales orders, invoices, purchase orders, work orders,
planning, global search, PDF and CSV output, six themes shared with OpenSchematix, and a read-only connection to
RevisionWorx (linked documents, BOM import from released revisions, revision stamps on work orders, out-of-step
warnings and open engineering changes).

- **Serial numbers for units made, registered in RevisionWorx.** An item can be made with serial numbers. Completing its
  work order takes the serial of each unit (one per unit, each new in the company), brings each into stock under its
  serial and lists it on the work order. With RevisionWorx connected, they are registered in its unit register as built
  (`revisionworx link unit-register`, with a txid from the completion, so a retry never registers twice): the one write
  OpenMeridian makes to RevisionWorx, by the Director's decision. What RevisionWorx refuses stays listed, with its
  reason, and **Register in RevisionWorx** tries again.
- **Company file format 2.** Older files are upgraded when opened, after a verified copy of the file as it was is kept
  beside it (`NAME (format 1 backup).meridian`). See [docs/COMPANY_FILE.md](docs/COMPANY_FILE.md).
- **Lots.** An item bought or made can be tracked by lot. Receiving it asks for the supplier's lot; completing a work
  order asks which lots went in (filled in oldest first, for you to check) and brings what it makes in as a lot of its
  own (the work order's number, unless you give one); shipping and adjusting say which lot. The company file itself
  refuses a move of a lot-tracked item without its lot, or one that takes more than a lot has. **Trace** (an item's
  **Lots** tab, or a work order's lots) shows where a lot came from and where it went: the lots and units made from it,
  the customers it was shipped to, what's still in stock, and where the trail stops, with **Save as CSV**. Search finds
  lots too. The sample company has a hose kit bought in lots and manifolds made in lots.
- **Trees follow the theme** (the trace's): on dark and high-contrast themes they were white, with light text.
- **Company file format 3** adds lots. Format 2 files are upgraded when opened, with a verified copy kept beside them
  first (`NAME (format 2 backup).meridian`).
