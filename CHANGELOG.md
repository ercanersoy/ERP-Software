# Changelog

All notable changes of ERP-Software. Schema versions are explained in
`docs/*/DATABASES.md` ("Updates"); the database is migrated automatically on start.

## Unreleased

Schema version 2. Take a full backup before updating.

### Fixed – database portability

The test suite now runs on SQLite and PostgreSQL (`ERP_TEST_DB`).

- PostgreSQL databases with the SQL_ASCII encoding returned text as bytes, so
  nobody could log in. Connections now always use UTF-8, and the setup
  wizard warns when a PostgreSQL database is not UTF8.
- Turkish-aware, case-insensitive search did not work on PostgreSQL databases
  with the C/POSIX locale. It now works with every locale.
- SQLite silently rounded decimal and currency values to about 15 significant
  digits. Values are now stored exactly; existing SQLite databases are
  converted (schema version 2).
- Texts longer than their database column (labels, default values, help
  texts, choice options, currency codes, title field, MIME types) caused
  HTTP 500 on PostgreSQL, MySQL and SQL Server. They are now validated.
- Very large sort orders no longer overflow the database column.

### Fixed – application

- Decimal values with too many digits (e.g. `1E+30`) caused HTTP 500.
- Ids that do not fit into 64 bits in URLs, and characters such as `²` in
  numeric inputs, caused HTTP 500.
- The setup wizard did not validate the database system, language, time
  zone and currency.
- A stored file could be attached to two records; deleting one record then
  deleted the other's file. Such requests are now refused (`file_in_use`).
- CSV import reported wrong line numbers for some errors.
- Upload errors were shown on the wrong file field.
- Records created in the web forms or by CSV import were not pushed to
  WebSocket clients.
- E-mail addresses were not validated in "My account" and the user form.
- An administrator who removed their own admin role landed on a 403 page.
- API file downloads lost non-ASCII letters in file names.
- An empty API filter (`?field=`) never matched; it now finds records
  without a value.
- Return addresses with control characters after login caused HTTP 500.
- Deleting a missing menu or API key reported success.
- System information merged data screens with the same label.
- Saving the form of a data screen without fields created empty records.
- The API counted rejected writes against the minimum write interval.
- A full restore could fail half-way on invalid field definitions after
  tables had been dropped (MySQL/MariaDB commit DDL at once). The file is
  now validated completely first.
- Importing data formats into an existing installation failed when a new
  link field pointed to a data screen created by the same import.

### Fixed – editing, import and validation (third review)

- Editing a record silently erased a choice value whose option had been
  removed later; such values are now shown as "no longer offered" and kept.
- Editing a record silently removed a link to a record beyond the first
  1000 records of the linked data screen.
- Date-times with an invalid time ("2026-01-31 25:00") were saved as
  midnight instead of being refused.
- "-0" was stored as "-0.00", which differs from "0.00" in unique checks and
  filters.
- An administrator changing their own password in the user form was logged
  out.
- Appending a data export (e.g. twice, or into another installation) attached
  one stored file to several records, or linked records to an unrelated file
  with the same id. Files are now renumbered or copied as needed.
- A table change refused by the database (e.g. MySQL's row size limit for
  many long text fields) showed an HTTP 500 page instead of a message.

### Fixed – MySQL/MariaDB and packaging (fourth review)

The test suite now also runs on MariaDB, with the `mysql` and `mariadb` settings.

- A full restore always failed on MySQL/MariaDB ("Duplicate entry
  'schema_version'"): MySQL reports changed instead of matched rows for
  UPDATE. Connections now use FOUND_ROWS, and the restore no longer relies
  on the row count.
- The in-app help (Help menu, API documentation link) answered 404 for
  every page when the program was installed with `pip install .`: the
  documentation is now installed with the package.
- Building the package failed with setuptools 69-76 although pyproject.toml
  allowed them; the minimum is now setuptools 77.

### Added – usability and touch screens

- Touch screens: touch targets of at least 44 px, no zoom on input focus,
  no keyboard hints, a "Back" button, no automatic focus that would open the
  on-screen keyboard, no auto-capitalisation of technical names.
- Warning before unsaved form input is discarded; protection against
  double submission of forms.
- Wide tables scroll inside their own box; the Save bar sticks to the bottom
  of long forms on small screens; delete actions are red.
- A "?" button opens the keyboard shortcut list; the list closes on a click
  outside it and gives the focus back. Sorted columns, the monitor's pause
  button and search fields have better accessibility attributes.
- Currency fields show `12500.50` instead of `12500.5000` when editing.

### Documentation

- Detailed docstrings and comments throughout the source code.
- User guide: touch screens, field length limits, files belonging to one
  record. Database guide: PostgreSQL encoding, exact decimals, updates and
  schema versions. API guide: empty filters, number precision, new error
  codes, rate limit behaviour, WebSocket events from all sources. Backup
  guide: restore validation and import order.

## 1.0.0

First release.
