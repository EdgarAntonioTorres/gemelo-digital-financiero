"""
Pruebas de `assistant/rubrica_t082.py`: selección de la muestra y calificación.
Sin Ollama ni BD.
"""

from __future__ import annotations

import unittest

from assistant import rubrica_t082 as rb


def _registros(n_buenos=30, n_con_bandera=5, n_guardrail=3):
    regs = []
    for i in range(n_buenos):
        regs.append(
            dict(
                perfil="Ana primeriza",
                corrida=1,
                qid=f"B{i}",
                pregunta="q",
                categoria="PERFIL",
                respuesta="ok",
                banderas=[],
                guardrail=False,
            )
        )
    for i in range(n_con_bandera):
        regs.append(
            dict(
                perfil="Ana más madura",
                corrida=2,
                qid=f"F{i}",
                pregunta="q",
                categoria="PERFIL",
                respuesta="mal",
                banderas=["siglas_solas=['IRFI']"],
                guardrail=False,
            )
        )
    for i in range(n_guardrail):
        regs.append(
            dict(
                perfil="Ana más madura",
                corrida=3,
                qid=f"G{i}",
                pregunta="q",
                categoria="PLAN",
                respuesta="g",
                banderas=[],
                guardrail=True,
            )
        )
    return regs


def _llenar(md: str, n_revisadas: int, cumplen: int) -> str:
    """Marca n_revisadas respuestas; las primeras `cumplen` cumplen los 3 criterios."""
    bloques = md.split("\n### ")
    salida = [bloques[0]]
    for i, b in enumerate(bloques[1:]):
        if i < n_revisadas:
            b = b.replace("Revisada: [ ]", "Revisada: [x]")
            b = b.replace("Cifras: [ ]", "Cifras: [x]")
            if i < cumplen:
                b = (
                    b.replace("[ ] se entiende", "[x] se entiende")
                    .replace("[ ] empieza", "[x] empieza")
                    .replace("[ ] evita", "[x] evita")
                )
        salida.append(b)
    return "\n### ".join(salida)


class TestMuestra(unittest.TestCase):
    def test_incluye_todas_las_destacadas_hasta_el_tope_y_algunas_al_azar(self):
        m = rb.construir_muestra(_registros())
        self.assertEqual(len(m), 8 + 10)  # 8 destacadas (< tope de 12) + 10 al azar
        ids = {r["qid"] for r in m}
        self.assertTrue({f"F{i}" for i in range(5)} <= ids)
        self.assertTrue({f"G{i}" for i in range(3)} <= ids)

    def test_respeta_el_tope_de_destacadas(self):
        m = rb.construir_muestra(
            _registros(n_con_bandera=20), destacadas_max=12, al_azar=0
        )
        self.assertEqual(len(m), 12)

    def test_es_reproducible_con_la_misma_semilla(self):
        a = [r["qid"] for r in rb.construir_muestra(_registros())]
        b = [r["qid"] for r in rb.construir_muestra(_registros())]
        self.assertEqual(a, b)

    def test_semilla_distinta_cambia_el_azar(self):
        a = [r["qid"] for r in rb.construir_muestra(_registros(), semilla=1)]
        b = [r["qid"] for r in rb.construir_muestra(_registros(), semilla=2)]
        self.assertNotEqual(a, b)

    def test_pocas_respuestas_no_truena(self):
        self.assertEqual(len(rb.construir_muestra(_registros(2, 0, 0))), 2)


class TestCalificar(unittest.TestCase):
    def setUp(self):
        self.md = rb.escribir_muestra(rb.construir_muestra(_registros()), "t082_prueba")

    def test_el_archivo_trae_las_casillas(self):
        self.assertEqual(self.md.count("Revisada: [ ]"), 18)
        self.assertIn("se entiende sin saber de finanzas", self.md)

    def test_sin_llenar_es_muestra_insuficiente(self):
        r = rb.calificar(self.md)
        self.assertEqual(r["revisadas"], 0)
        self.assertTrue(r["veredicto"].startswith("MUESTRA INSUFICIENTE"))

    def test_aprueba_con_80_por_ciento_o_mas(self):
        r = rb.calificar(_llenar(self.md, n_revisadas=18, cumplen=15))  # 83%
        self.assertEqual(r["revisadas"], 18)
        self.assertEqual(r["cumplen_los_3"], 15)
        self.assertEqual(r["veredicto"], "APRUEBA")

    def test_no_aprueba_con_menos_de_80(self):
        r = rb.calificar(_llenar(self.md, n_revisadas=18, cumplen=12))  # 67%
        self.assertTrue(r["veredicto"].startswith("NO APRUEBA: 67%"))

    def test_una_respuesta_que_falla_todo_cuenta_en_contra(self):
        # sin la casilla "Revisada" esa respuesta parecería no revisada y sesgaría a favor
        r = rb.calificar(_llenar(self.md, n_revisadas=16, cumplen=12))
        self.assertEqual(r["revisadas"], 16)
        self.assertEqual(r["cumplen_los_3"], 12)

    def test_cifras_que_no_coinciden_bloquean_aunque_pase_el_porcentaje(self):
        md = _llenar(self.md, n_revisadas=18, cumplen=18)
        md = md.replace("Cifras: [x]", "Cifras: [ ]", 1)
        r = rb.calificar(md)
        self.assertTrue(r["veredicto"].startswith("NO APRUEBA: alguna respuesta"))

    def test_menos_de_15_revisadas_no_basta(self):
        r = rb.calificar(_llenar(self.md, n_revisadas=10, cumplen=10))
        self.assertTrue(r["veredicto"].startswith("MUESTRA INSUFICIENTE"))


if __name__ == "__main__":
    unittest.main()
