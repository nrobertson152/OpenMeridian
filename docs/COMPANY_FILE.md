# The company file (`.meridian`)

A `.meridian` file is one SQLite 3.37+ database holding one company.

- **Identity:** `PRAGMA application_id` is `0x4F4D4552` ("OMER"). Anything else is refused with a message, as is a file
  that fails `PRAGMA quick_check`.
- **Version:** `PRAGMA user_version` is the format version, currently **1**. A file from a newer version is refused, not
  guessed at. A future format change adds a tested migration here and raises the number.
- **Tables** are `STRICT`, with foreign keys on.
- **Money** is integer cents and **quantities** are integer thousandths, so totals never drift.
- **Append-only:** triggers in the file reject any `UPDATE` or `DELETE` on `stock_moves` and `audit`.
- **Stock** is never stored as a number to be edited: on-hand is the sum of `stock_moves`.
- **Transactions:** each operation is one `BEGIN IMMEDIATE` transaction with SQLite's rollback journal and
  `synchronous=FULL`, so a crash leaves the state before or after it, not between. Backups use SQLite's backup API, write
  to a temporary name, and never overwrite.
- **Numbers** (`SO-00001`) come from `sequences`, and a number is never reused.
- **RevisionWorx references** are stored as document and revision ids and labels. They are references only: no file
  from a workspace is copied in, and nothing is written back.

## Assumptions

- One writer at a time on a local disk. SQLite makes concurrent access safe on a local disk, but network filesystems
  often don't honour its locks, so a shared file on a network drive is untested and unsupported.

## Version history

| Version | Change |
|---|---|
| 1 | First format |
