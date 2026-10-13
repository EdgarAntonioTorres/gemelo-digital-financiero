"""
Pruebas de `assistant/indicadores.py` y `assistant/categorias_gasto.py` y de su
integración con Centavo (Sesión 36, comentarios del mentor). Los números de las
dos Anas salen de los datos reales del CSV de Personal Finance Tracker.
Sin Ollama ni BD.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from assistant import categorias_gasto as cg
from assistant import contexto_centavo as ctx
from assistant import indicadores as ind
from assistant import plan_engine as pe
from assistant import router
from assistant import verificaciones_respuesta as vr


# Datos reales (CSV original, 1 coincidencia por valor):
#   primeriza: gasto 3077.46, ingreso 3704.29, esencial 1786.51,
#              discrecional 464.49, vivienda 1071.82
#   madura   : gasto 2443.44, ingreso 3854.89, esencial 1740.00,
#              discrecional 753.26, vivienda 1086.19
def _cargado(
    ingreso,
    gasto,
    ratio,
    fondo,
    meta,
    inv,
    rid,
    esencial,
    discrecional,
    vivienda,
    irfi,
    ica,
):
    perfil = pe.PerfilFinanciero(ingreso, gasto, ratio, fondo, meta, False, inv, rid)
    detalle = {
        "suscripciones_activas": 3,
        "proporcion_esencial": esencial / (esencial + discrecional),
        "gasto_esencial_declarado": esencial,
        "gasto_discrecional_declarado": discrecional,
        "vivienda_mensual": vivienda,
    }
    return SimpleNamespace(
        record_id=rid,
        perfil=perfil,
        plan=pe.generar_plan(perfil),
        comportamiento={"income_type": "Freelance"},
        detalle=detalle,
        irfi=irfi,
        ica=ica,
    )


def primeriza():
    return _cargado(
        3704.29,
        3077.46,
        0.58,
        540.88,
        2194.05,
        140.81,
        "PFT_0000636",
        1786.51,
        464.49,
        1071.82,
        0.52,
        0.27669086,
    )


def madura():
    return _cargado(
        3854.89,
        2443.44,
        0.17,
        1286.49,
        2346.98,
        202.27,
        "PFT_0002539",
        1740.00,
        753.26,
        1086.19,
        0.4175,
        0.48293253,
    )


class TestEtiquetas(unittest.TestCase):
    def test_irfi_cortes(self):
        self.assertEqual(ind.lectura_irfi(0.20).etiqueta, "Bajo")
        self.assertEqual(
            ind.lectura_irfi(0.349).etiqueta, "Moderado"
        )  # se muestra 0.35
        self.assertEqual(ind.lectura_irfi(0.35).etiqueta, "Moderado")
        self.assertEqual(ind.lectura_irfi(0.5999).etiqueta, "Alto")  # se muestra 0.60
        self.assertEqual(ind.lectura_irfi(0.90).etiqueta, "Alto")

    def test_ica_cortes(self):
        self.assertEqual(ind.lectura_ica(0.70).etiqueta, "Alta")
        self.assertEqual(ind.lectura_ica(0.60).etiqueta, "Media")
        self.assertEqual(ind.lectura_ica(0.351).etiqueta, "Baja")  # se muestra 0.35
        self.assertEqual(ind.lectura_ica(0.10).etiqueta, "Baja")

    def test_la_etiqueta_coincide_con_el_valor_mostrado(self):
        # nunca "0.35 — Bajo" con un rango que dice que 0.35 es Moderado
        for v in (0.345, 0.349, 0.351, 0.595, 0.599):
            mostrado = round(v, 2)
            self.assertEqual(
                ind.lectura_irfi(v).etiqueta, ind.lectura_irfi(mostrado).etiqueta
            )

    def test_tonos(self):
        self.assertEqual(ind.lectura_irfi(0.1).tono, "bueno")
        self.assertEqual(ind.lectura_irfi(0.9).tono, "atencion")
        self.assertEqual(ind.lectura_irfi(0.1).badge, "badge-emerald")
        self.assertEqual(ind.lectura_ica(0.1).badge, "badge-coral")

    def test_faltante_no_se_inventa(self):
        self.assertIsNone(ind.lectura_irfi(None))
        self.assertIsNone(ind.lectura_ica(None))
        self.assertIsNone(ind.salud_financiera(None, 0.5))
        self.assertIsNone(ind.salud_financiera(0.5, None))
        self.assertIsNone(ind.lectura_salud(None))
        self.assertEqual(ind.lineas_para_centavo(None, None), [])


class TestSalud(unittest.TestCase):
    def test_formula_con_datos_reales(self):
        self.assertEqual(ind.salud_financiera(0.52, 0.27669086), 36)  # primeriza
        self.assertEqual(ind.salud_financiera(0.4175, 0.48293253), 52)  # madura

    def test_etiquetas_con_datos_reales(self):
        self.assertEqual(ind.lectura_salud(36).etiqueta, "Vulnerable")
        self.assertEqual(ind.lectura_salud(52).etiqueta, "Estable")

    def test_cortes_exactos(self):
        self.assertEqual(ind.lectura_salud(75).etiqueta, "Óptima")
        self.assertEqual(ind.lectura_salud(74).etiqueta, "Estable")
        self.assertEqual(ind.lectura_salud(50).etiqueta, "Estable")
        self.assertEqual(ind.lectura_salud(49).etiqueta, "Vulnerable")

    def test_es_entera_y_acotada(self):
        self.assertIsInstance(ind.salud_financiera(0.5, 0.5), int)
        self.assertEqual(ind.salud_financiera(0.0, 1.0), 100)
        self.assertEqual(ind.salud_financiera(1.0, 0.0), 0)
        self.assertEqual(ind.salud_financiera(2.0, -1.0), 0)  # fuera de rango: se acota


class TestParaCentavo(unittest.TestCase):
    def test_lineas_con_etiqueta_oficial_y_rango(self):
        t = "\n".join(ind.lineas_para_centavo(0.52, 0.27669086))
        self.assertIn("índice de riesgo financiero inicial", t)
        self.assertIn("Etiqueta oficial: Moderado", t)
        self.assertIn("Etiqueta oficial: Baja", t)
        self.assertIn("Salud financiera: 36 de 100. Etiqueta oficial: Vulnerable", t)
        self.assertIn("Bajo: menos de 0.35", t)
        self.assertIn("estimado", t)

    def test_el_contexto_de_centavo_trae_las_etiquetas(self):
        t = ctx.contexto_perfil(primeriza(), "Ana")
        self.assertIn("Etiqueta oficial: Moderado", t)
        self.assertNotIn("Individual", t)

    def test_permitidas_son_solo_las_de_la_persona(self):
        p = ind.etiquetas_permitidas(0.52, 0.27669086)  # IRFI Moderado, ICA Baja
        self.assertIn("moderado", p)
        self.assertIn("baja capacidad de ahorro", p)
        self.assertNotIn("riesgo alto", p)
        self.assertNotIn("alta capacidad", p)


class TestGuardrailConEtiquetasOficiales(unittest.TestCase):
    PERMITIDAS = ind.etiquetas_permitidas(0.52, 0.27669086)  # Moderado / Baja

    def test_la_etiqueta_oficial_ya_no_se_marca(self):
        t = "Tu IRFI es 0.52, un riesgo moderado."
        self.assertTrue(
            vr.umbral_inventado(t)
        )  # sin permitidas: se marca (comportamiento original)
        self.assertEqual(vr.umbral_inventado(t, self.PERMITIDAS), [])

    def test_otra_etiqueta_si_se_marca(self):
        t = "Tu IRFI es 0.52, lo que significa un riesgo alto."
        self.assertTrue(vr.umbral_inventado(t, self.PERMITIDAS))

    def test_baja_capacidad_permitida_si_el_ica_es_bajo(self):
        t = "Tu ICA es 0.28: tienes una baja capacidad de ahorro."
        self.assertEqual(vr.umbral_inventado(t, self.PERMITIDAS), [])
        self.assertTrue(
            vr.umbral_inventado("Tienes una alta capacidad de ahorro.", self.PERMITIDAS)
        )

    def test_ideal_nunca_se_permite(self):
        self.assertTrue(
            vr.umbral_inventado("Tu IRFI debería estar en lo ideal.", self.PERMITIDAS)
        )

    def test_frases_de_juicio_respeta_las_permitidas(self):
        t = "Tu IRFI es 0.52, un riesgo moderado. Tu deuda es un problema."
        self.assertEqual(
            vr.frases_de_juicio(t, self.PERMITIDAS), ["Tu deuda es un problema."]
        )

    def test_el_guardrail_no_regenera_si_solo_usa_la_etiqueta_oficial(self):
        llamadas = []
        r, info = router.aplicar_guardrail(
            "Tu IRFI es 0.52, un riesgo moderado.",
            "IRFI 0.52",
            lambda n: llamadas.append(n) or "x",
            permitidas=self.PERMITIDAS,
        )
        self.assertEqual(llamadas, [])
        self.assertFalse(info["reintento"])

    def test_el_prompt_dice_inicial(self):
        self.assertIn(
            "Índice de Riesgo Financiero Inicial", router.SYSTEM_PROMPT_TEMPLATE
        )
        self.assertNotIn("Individual", router.SYSTEM_PROMPT_TEMPLATE)


class TestDesglose(unittest.TestCase):
    def test_primeriza_las_categorias_caben_y_sobra_sin_categorizar(self):
        c = primeriza()
        g = cg.desde_detalle(c.perfil, c.detalle)
        self.assertAlmostEqual(g.vivienda, 1071.82)
        self.assertAlmostEqual(g.otros_basicos, 714.69, places=2)  # 1786.51 - 1071.82
        self.assertAlmostEqual(g.flexibles, 464.49)
        self.assertAlmostEqual(g.categorizado, 2251.00, places=2)
        self.assertAlmostEqual(g.sin_categorizar, 826.46, places=2)
        self.assertTrue(g.cuadra_con_el_total)
        self.assertEqual(g.exceso, 0.0)
        self.assertEqual(g.denominador, g.gasto_total)
        # las partes suman el gasto total
        self.assertAlmostEqual(sum(m for _, m in g.partes()), 3077.46, places=2)
        self.assertEqual([n for n, _ in g.partes()][-1], cg.SIN_CATEGORIZAR)

    def test_madura_las_categorias_superan_el_total(self):
        c = madura()
        g = cg.desde_detalle(c.perfil, c.detalle)
        self.assertAlmostEqual(g.categorizado, 2493.26, places=2)
        self.assertAlmostEqual(g.exceso, 49.82, places=2)
        self.assertEqual(g.sin_categorizar, 0.0)
        self.assertFalse(g.cuadra_con_el_total)
        self.assertGreater(g.cobertura, 1.0)
        # no se inventa una barra "sin categorizar": solo las 3 categorías
        self.assertEqual(
            [n for n, _ in g.partes()], [cg.VIVIENDA, cg.OTROS_BASICOS, cg.FLEXIBLES]
        )
        # los porcentajes se leen sobre lo categorizado y suman 100
        self.assertAlmostEqual(
            sum(g.porcentaje(m) for _, m in g.partes()), 100.0, places=6
        )

    def test_vivienda_como_porcentaje_del_ingreso(self):
        g = cg.desde_detalle(primeriza().perfil, primeriza().detalle)
        self.assertAlmostEqual(g.vivienda_pct_ingreso * 100, 28.9, places=1)

    def test_recorte_ilustrativo_es_aritmetica_de_un_si(self):
        g = cg.desde_detalle(primeriza().perfil, primeriza().detalle)
        self.assertAlmostEqual(g.recorte_ilustrativo(0.10), 46.449, places=3)

    def test_sin_las_columnas_nuevas_no_inventa(self):  # migración SQL sin correr
        c = primeriza()
        c.detalle = {"suscripciones_activas": 3, "proporcion_esencial": 0.79}
        self.assertIsNone(cg.desde_detalle(c.perfil, c.detalle))

    def test_nan_o_none_no_se_toman_como_dato(self):
        c = primeriza()
        c.detalle = dict(c.detalle, vivienda_mensual=float("nan"))
        self.assertIsNone(cg.desde_detalle(c.perfil, c.detalle))
        c.detalle = dict(c.detalle, vivienda_mensual=None)
        self.assertIsNone(cg.desde_detalle(c.perfil, c.detalle))

    def test_vivienda_mayor_que_el_esencial_no_da_negativos(self):
        g = cg.desglosar(2000, 800, 300, 900, 3000)
        self.assertEqual(g.otros_basicos, 0.0)

    def test_montos_negativos_se_rechazan(self):
        with self.assertRaises(ValueError):
            cg.desglosar(2000, -1, 300, 900, 3000)


class TestCentavoConCategorias(unittest.TestCase):
    def test_primeriza_contexto(self):
        t = ctx.contexto_perfil(primeriza(), "Ana")
        self.assertIn("vivienda $1,072 (29% del ingreso)", t)
        self.assertIn("otros gastos básicos $715", t)
        self.assertIn("gastos flexibles $464", t)
        self.assertIn("sin categorizar $826 (27% del gasto total)", t)
        self.assertIn("NO existen categorías como comida", t)

    def test_madura_dice_que_las_categorias_pasan_del_total(self):
        t = ctx.contexto_perfil(madura(), "Ana")
        self.assertIn("suman $2,493, $50 más que el gasto total ($2,443)", t)
        self.assertIn("proporciones, no como partes del total", t)
        self.assertNotIn("sin categorizar", t)

    def test_sin_migracion_cae_a_la_proporcion(self):
        c = primeriza()
        c.detalle = {"suscripciones_activas": 3, "proporcion_esencial": 0.7936}
        t = ctx.contexto_perfil(c)
        self.assertIn("Proporción de gasto esencial: 79%", t)
        self.assertNotIn("vivienda", t)

    def test_plan_trae_el_ejemplo_de_recorte_calculado(self):
        t = ctx.bloque_de_codigo("PLAN", primeriza(), "¿En qué puedo reducir gastos?")
        self.assertIn("recortara 10% de sus gastos flexibles, ahorraría $46 al mes", t)
        self.assertIn("aritmética de un 'si', no una estadística", t)

    def test_las_cifras_del_contexto_estan_respaldadas(self):
        # el verificador no debe marcar ningún monto que el propio contexto trae
        c = primeriza()
        contexto = ctx.contexto_perfil(c, "Ana")
        respuesta = "Tu vivienda es $1,072, tus gastos flexibles son $464, con $826 sin categorizar."
        self.assertEqual(
            vr.cifras_sin_respaldo(respuesta, contexto, solo_dolares=True), []
        )


if __name__ == "__main__":
    unittest.main()
