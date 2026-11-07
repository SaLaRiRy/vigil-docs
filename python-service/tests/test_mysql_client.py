from core.mysql_client import MySQLClient


class FakeCursor:
    def __init__(self, status="PROCESSING"):
        self.status = status
        self.rowcount = 0
        self.executed = []
        self.many = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT status FROM knowledge_doc"):
            self.rowcount = 1
        elif normalized.startswith("UPDATE knowledge_doc"):
            self.rowcount = 1
        elif normalized.startswith("UPDATE document_processing"):
            # MySQL reports changed rows rather than matched rows when
            # CLIENT_FOUND_ROWS is disabled. Re-saving NULL/0 is a no-op.
            self.rowcount = 0

    def executemany(self, sql, data):
        self.many.append((sql, list(data)))

    def fetchone(self):
        return (self.status,)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.transactions = 0

    def is_connected(self):
        return True

    def cursor(self):
        return self.fake_cursor

    def start_transaction(self):
        self.transactions += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_completed_transaction_succeeds_when_metadata_update_is_a_noop():
    cursor = FakeCursor(status="PROCESSING")
    connection = FakeConnection(cursor)
    client = MySQLClient()
    client.connection = connection

    result = client.complete_document(
        65,
        [{"page_content": "软件工程课程内容", "chunk_index": 0}],
    )

    assert result == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_completion_does_not_commit_after_document_was_deleted():
    cursor = FakeCursor(status="DELETED")
    connection = FakeConnection(cursor)
    client = MySQLClient()
    client.connection = connection

    result = client.complete_document(
        65,
        [{"page_content": "软件工程课程内容", "chunk_index": 0}],
    )

    assert result == 0
    assert connection.commits == 0
    assert connection.rollbacks == 1
