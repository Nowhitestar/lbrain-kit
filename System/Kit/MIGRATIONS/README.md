<!-- ownership: kit -->
# Migrations

Each release that requires user action adds one file named `<from>-to-<to>.md`. A migration must state:

- affected Kit-owned, Seeded, and User-owned paths;
- preconditions and backup expectations;
- exact manual steps;
- validation and rollback steps;
- whether the action is required or optional.

No migration may silently overwrite Seeded or User-owned content.
