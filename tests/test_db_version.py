from agents.db_version import SchemaVersionTracker

def test_initial_version_is_zero(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    assert tracker.current_version() == 0

def test_apply_migration_increments_version(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    def migration_1(conn):
        conn.execute("CREATE TABLE test_table (id TEXT PRIMARY KEY)")
    tracker.apply(1, migration_1)
    assert tracker.current_version() == 1

def test_skip_already_applied(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    call_count = 0
    def migration_1(conn):
        nonlocal call_count
        call_count += 1
        conn.execute("CREATE TABLE test_table (id TEXT PRIMARY KEY)")
    tracker.apply(1, migration_1)
    tracker.apply(1, migration_1)
    assert call_count == 1

def test_multiple_migrations_in_order(tmp_path):
    tracker = SchemaVersionTracker(tmp_path / "test.db")
    tracker.apply(1, lambda c: c.execute("CREATE TABLE t1 (id TEXT)"))
    tracker.apply(2, lambda c: c.execute("CREATE TABLE t2 (id TEXT)"))
    assert tracker.current_version() == 2
