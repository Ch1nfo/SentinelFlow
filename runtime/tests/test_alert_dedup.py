from __future__ import annotations

import sys
import unittest
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import tempfile
import os

from sentinelflow.alerts.dedup import AlertDedupStore
import sentinelflow.alerts.dedup


class AlertDedupStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fd, self.temp_db = tempfile.mkstemp()
        sentinelflow.alerts.dedup.DB_PATH = self.temp_db

    def tearDown(self) -> None:
        os.close(self.fd)
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)
    def test_mark_processing_done_and_failed(self) -> None:
        store = AlertDedupStore()

        self.assertFalse(store.seen("E-1"))

        store.mark_processing("E-1")
        self.assertTrue(store.is_processing("E-1"))
        self.assertTrue(store.seen("E-1"))

        store.mark_failed("E-1")
        self.assertFalse(store.is_processing("E-1"))
        self.assertFalse(store.is_completed("E-1"))
        self.assertFalse(store.seen("E-1"))

        store.mark_processing("E-1")
        store.mark_done("E-1")
        self.assertFalse(store.is_processing("E-1"))
        self.assertTrue(store.is_completed("E-1"))
        self.assertTrue(store.seen("E-1"))
