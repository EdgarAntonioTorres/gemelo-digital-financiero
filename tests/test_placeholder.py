"""
Placeholder temporal para que el job `test` del CI (t024) no falle por
'no tests collected' mientras la suite de tests real (t086, Fase 6) no
está implementada.

Cuando se agreguen tests reales en tests/, este archivo puede borrarse.
"""


def test_placeholder():
    """Test trivial que siempre pasa — solo evita que pytest salga con
    código 5 (no tests found) contra una carpeta tests/ vacía."""
    assert True
