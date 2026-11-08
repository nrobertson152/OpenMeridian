# The company file (`.meridian`)

A `.meridian` file is one SQLite 3.37+ database holding one company.

- **Identity:** `PRAGMA application_id` is `0x4F4D4552` ("OMER"). Anything else is refused with a message, as is a file
  that fails `PRAGMA quick_check`.
- **Version:** `PRAGMA user_version` is the format version, currently **3**. A file from a newer version is refused, not
  guessed at. An older file is upgraded when it is opened (below).
- **Tables** are `STRICT`, with foreign keys on.
- **Money** is integer cents and **quantities** are integer thousandths, so totals never drift.
- **Append-only:** triggers in the file reject any `UPDATE` or `DELETE` on `stock_moves` and `audit`. Other triggers
  enforce the lot rules (*Lots*, below).
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

- `items.tracking` is `none`, `serial` or (from format 3) `lot`. Only an item that is made (`kind = 'make'`) can be
  `serial`, and tracking can only change while none of the item is in stock. In format 2, `lot` was reserved: the file
  accepted the word and OpenMeridian refused to set it.
- `stock_moves.serial` and `stock_moves.lot` say which unit or lot a move was. A unit made with a serial comes into stock
  as its own move of one, carrying its serial. `lot` was always empty in format 2.
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

## Lots (format 3)

An item tracked by lot (`items.tracking = 'lot'`), bought or made, says which lot at every move:

- **Receiving** a purchase order line, the lot it came in as (the supplier's lot or batch number). A line that came in
  as two lots is received twice.
- **Using** it on a work order, which lots went in, and how much of each. OpenMeridian fills them in oldest first (by
  each lot's first move) for someone to check, and records only what they say; it never chooses a lot by itself.
- **Making** it, the lot it comes in as: the work order's number for its first completion, then the number and the
  completion (`WO-00012-2`), unless someone names another.
- **Shipping** it, which lots it ships from. **Adjusting** it, which lot (a new one is allowed when stock goes up).

A lot is kept in Unicode NFC, single-spaced, without control characters, at most 100 characters. It belongs to its item
(lot `2306` of one item has nothing to do with lot `2306` of another), and an item's lot is one lot whatever its ASCII
case: the file keeps the spelling it was first given.

The file enforces the rules itself, so no program can break them:

- `stock_moves_lot_named`: a move of an item tracked by lot names its lot, and a move of any other item names none.
- `stock_moves_lot_covered`: a move out of a lot can't take more than the lot has.
- `items_tracking_needs_no_stock`: an item starts or stops being tracked (by serial or lot) only while none is in
  stock, so all of an item's stock is always under the tracking it has now.

`stock_moves.batch` is which completion of the work order in `ref` a `consume` or `produce` move was part of, counting
from 1 on each work order (the same number `wo_units.batch` gives its units); `0` for any other move and for every move
written before format 3. A completion's number is one more than the highest either of them has for that work order, so
completions after an upgrade carry on from the units' numbering. Indexes on `(item_id, lot)` and `(ref, batch)` keep
tracing quick.

### Tracing a lot

A trace follows the ledger and nothing else:

- **Where it came from:** each move into the lot. A receipt names its purchase order and supplier. A completion names
  its work order and lists what that completion used (`ref` and `batch`), each component's lot traced back in turn.
- **Where it went:** each move out. A shipment names its sales order and customer. A use names its completion and lists
  what that completion made. A lot made is followed onward, whole: if more was added to that lot from elsewhere, that
  is followed too, so a recall can be wider than it needs to be but never narrower. Units made are listed by serial,
  with whether RevisionWorx has them; which serial a later shipment or work order took isn't recorded, so a unit ends
  its trail. An item made that isn't tracked ends the trail, and the trace says so.
- What's left in each lot reached is shown as in stock. A trace stops after 24 levels of assemblies and says so.

With RevisionWorx connected, **Where are they now?** asks its unit register, and only reads it:

- For each unit the lot went into, it says what the register has: status, customer, site and location. The unit is
  matched by the id RevisionWorx gave it when it was registered, or else by its serial (`link units`).
- It lists the units the register records any lot reached fitted in, now or before, that the ledger didn't reach. That
  covers the lot traced and every lot made from it (`link where-used --part-number ITEM --lot LOT --history`, RevisionWorx's
  `unit-where-used` feature). A spare fitted on site is the usual case: the ledger knows only that it was shipped. The item
  number is taken as the part number.
- Nothing is written to RevisionWorx, and nothing it says is kept in the company file. Saving the trace as CSV includes
  the answer.

**A supplier's recall.** A supplier announces a recall of lots it sent. On the supplier's page, **Recall…** lists the lots
received from that supplier, from purchase orders' receipts (`Company.lots_received`): by item and by the day they came
in, with how much came, the orders they came on and what's on hand now. Every lot listed is ticked; untick the ones the
recall doesn't name. **Trace these** traces them together (`Company.trace_lots`): what they reached, each unit, shipment,
stock and lot once, then each lot's own trace. **Where are they now?** and **Save as CSV** work as for one lot, asking
RevisionWorx about every lot reached. Nothing new is stored: no change to the company file.

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
`tests/data/format1.meridian` is a company file made by the first version, and `tests/data/format2.meridian` one made
with format 2 (the sample company, and a power unit made with a serial number and registered); the tests upgrade both.

The step to format 3 first sets any item marked `lot` back to `none`. Format 2 had no lots (OpenMeridian refused to set
one, so an item marked `lot` was marked outside it, and none of its stock names a lot), and the lot rules can't hold for
stock that names none. Its stock is unchanged. Moves written before format 3 keep `batch` 0 and name no lot.

## Assumptions

- One writer at a time on a local disk. SQLite makes concurrent access safe on a local disk, but network filesystems
  often don't honour its locks, so a shared file on a network drive is untested and unsupported.
- A file upgraded to format 2 or 3 can't be opened by an OpenMeridian that knows only an older format: it refuses newer
  formats with a message. The copy kept beside it can.
- Other programs that read company files check the format too. FieldWorx's bridge reads items and the sum of the stock
  ledger, which format 3 doesn't change, and lists the formats it reads.

## Version history

| Version | Change |
|---|---|
| 1 | First format |
| 2 | Serial numbers for items made: `items.tracking`, `stock_moves.serial` and `stock_moves.lot`, `wo_units`, `settings.company_id`. `lot` is reserved. |
| 3 | Lots: `items.tracking = 'lot'` for items bought or made, `stock_moves.lot` named on every move of one, `stock_moves.batch`, the lot triggers and two indexes. Items marked `lot` in format 2 go back to `none`. |
