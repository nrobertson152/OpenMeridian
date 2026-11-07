# The company file (`.meridian`)

A `.meridian` file is one SQLite 3.37+ database holding one company.

- **Identity:** `PRAGMA application_id` is `0x4F4D4552` ("OMER"). Anything else is refused with a message, as is a file
  that fails `PRAGMA quick_check`.
- **Version:** `PRAGMA user_version` is the format version, currently **2**. A file from a newer version is refused, not
  guessed at. An older file is upgraded when it is opened (below).
- **Tables** are `STRICT`, with foreign keys on.
- **Money** is integer cents and **quantities** are integer thousandths, so totals never drift.
- **Append-only:** triggers in the file reject any `UPDATE` or `DELETE` on `stock_moves` and `audit`.
- **Stock** is never stored as a number to be edited: on-hand is the sum of `stock_moves`.
- **Transactions:** each operation is one `BEGIN IMMEDIATE` transaction with SQLite's rollback journal and
  `synchronous=FULL`, so a crash leaves the state before or after it, not between. Backups use SQLite's backup API, write
  to a temporary name, pass `PRAGMA integrity_check` and never overwrite.
- **Numbers** (`SO-00001`) come from `sequences`, and a number is never reused.
- **The company's id** (`settings.company_id`, 32 hex digits) is made when the company is, or when its file is upgraded
  to format 2, and never changes. It keeps one company's registrations in RevisionWorx apart from another's.
- **RevisionWorx references** are stored as document and revision ids and labels. They are references only: no file
  from a workspace is copied in. The one thing written to RevisionWorx is described under *Units built*.

## Serial numbers and units built (format 2)

- `items.tracking` is `none` or `serial`. Only an item that is made (`kind = 'make'`) can be `serial`, and it can only
  change while none is in stock. `lot` is reserved for a later version: the file accepts the word, OpenMeridian refuses
  to set it.
- `stock_moves.serial` and `stock_moves.lot` say which unit or lot a move was. A unit made with a serial comes into stock
  as its own move of one, carrying its serial. `lot` is reserved and always empty in format 2.
- `wo_units` lists each unit a work order made: its `serial`, the completion it was made in (`batch`, counting from 1 on
  each work order), the day it was `made`, and what it was built as (`model`, the item number then, and `name`, the
  description then, at most 200 characters). These are fixed when it is made: triggers refuse to change them or to delete
  the row. A serial names one unit in the company, whatever the item (`UNIQUE`, ignoring ASCII case), as a serial does in
  RevisionWorx. Serials are stored in Unicode NFC, without control characters, at most 100 characters.
- `rw_unit` is the unit's id in RevisionWorx once it is registered there; a trigger refuses to change it after that.
  `rw_note` is what RevisionWorx said when it didn't register it, word for word, and is cleared when it does.

### Registering in RevisionWorx (the one write)

By the Director's decision (2026-11-07), OpenMeridian registers the units its own work orders build in RevisionWorx's
unit register, and writes nothing else there. Each completion is one call to `revisionworx -w WORKSPACE link
unit-register`, all of its units or none:

| Argument | Value |
|---|---|
| `--txid` | the first 32 hex digits of SHA-256 of `openmeridian/register/v1`, NUL, the company id, NUL, the work order number, NUL, the batch (in decimal) |
| `--serial` | each unit's serial, in the order made (this organization's serials: no issuer) |
| `--model`, `--name` | `model` and `name` as kept when they were made |
| `--status`, `--built` | `built`, and the day they were made |
| `--doc` | `DOCUMENT_ID@REVISION_ID` that the work order recorded when it was released, if it recorded one |
| `--evidence` | `work-order:` and the work order number |

Every attempt at a completion sends exactly this, even after its item was renamed, so RevisionWorx answers a repeat
with the units it already registered (`already-recorded`) and writes nothing. If a completion's txid was used in
RevisionWorx for something else (another copy of this company file registered a different completion under the same
work order number, say), RevisionWorx refuses (`txid-used`) and OpenMeridian says so. A refusal of any kind changes
nothing in RevisionWorx and is kept in `rw_note`; *Register in RevisionWorx* sends the whole completion again.

## Upgrading an older file

When OpenMeridian opens a file of an older format, it takes the write lock (`BEGIN IMMEDIATE`) and then:

1. If another OpenMeridian upgraded the file meanwhile, it stops: there is nothing to do.
2. A copy of the file as it is goes beside it, as `NAME (format N backup).meridian` (or `... backup 2`, and so on: never
   over an existing file), made with SQLite's backup API by a second connection reading beside the lock, and checked
   with `PRAGMA integrity_check`. If the copy can't be made, the file isn't changed and a message says so.
3. Every step from that format to this one, a line in the activity log (`format.upgrade`, naming the copy), the company
   id and the new `user_version` are one transaction. If any of it fails, it is rolled back and the file is left as it
   was.

A new file is made with the format-1 tables followed by the same steps, so a new file and an upgraded one are the same.
`tests/data/format1.meridian` is a company file made by the first version, and the tests upgrade it.

## Assumptions

- One writer at a time on a local disk. SQLite makes concurrent access safe on a local disk, but network filesystems
  often don't honour its locks, so a shared file on a network drive is untested and unsupported.
- A file upgraded to format 2 can't be opened by the first version of OpenMeridian, which refuses newer formats with a
  message. The copy kept beside it can.

## Version history

| Version | Change |
|---|---|
| 1 | First format |
| 2 | Serial numbers for items made: `items.tracking`, `stock_moves.serial` and `stock_moves.lot`, `wo_units`, `settings.company_id`. `lot` is reserved. |
