from __future__ import annotations

import socket

import pytest


def test_automated_tests_cannot_open_external_socket():
    with pytest.raises(AssertionError, match="must not open network"):
        socket.create_connection(("example.com", 443), timeout=0.01)
