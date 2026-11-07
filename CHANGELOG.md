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
