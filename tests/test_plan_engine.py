"""
Pruebas de `plan_engine` (t077 v2.3; parte de t086 — pruebas mínimas en /tests)

Solo biblioteca estándar (`unittest`): no agrega dependencias a
`requirements-streamlit.txt`. Los casos principales usan las cifras reales
de las dos Anas de la demo (las mismas del documento t077 v2.3 §9), y el
retiro se verifica contra una simulación mes a mes escrita aparte, no
contra la misma fórmula del módulo.

Uso, desde la raíz del proyecto (no necesita Postgres ni Ollama):

    docker compose run --rm --no-deps streamlit python -m unittest discover -s tests -v

Requiere esta línea en `volumes:` del servicio `streamlit` de
docker-compose.yml, junto a las otras dos (igual que `./docs`):

    - ./tests:/app/tests:ro

El contenedor trabaja en /app (= src/dashboard), de donde salen
`assistant.plan_engine` y `escenario_empleo_demo`. El comando no usa rutas
que empiecen con "/", a propósito: Git Bash en Windows las reescribe.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from assistant import plan_engine as pe

# --- Las dos Anas (cifras reales de Silver PFT / Gold; ver t077 v2.3 §9) ---
ANA_PRIMERIZA = dict(
    ingreso_mensual=3704.29,
    gasto_mensual=3077.46,
    ratio_endeudamiento=0.58,
    fondo_emergencia_usd=540.88,
    meta_ahorro_mensual=2194.05,
    meta_cumplida=False,
    inversion_mensual=140.81,
)
ANA_MADURA = dict(
    ingreso_mensual=3854.89,
    gasto_mensual=2443.44,
    ratio_endeudamiento=0.17,
    fondo_emergencia_usd=1286.49,
    meta_ahorro_mensual=2346.98,
    meta_cumplida=False,
    inversion_mensual=202.27,
)


def ana_primeriza() -> pe.PerfilFinanciero:
    return pe.PerfilFinanciero(**ANA_PRIMERIZA)


def ana_madura() -> pe.PerfilFinanciero:
    return pe.PerfilFinanciero(**ANA_MADURA)


def filas_gold(record_id: str, perfil: dict, ahorro: float):
    """Filas como las devuelve Postgres (los NUMERIC llegan como Decimal)."""
    comportamiento = {
        "record_id": record_id,
        "ingreso_mensual": Decimal(str(perfil["ingreso_mensual"])),
        "gasto_promedio_3m": Decimal(str(perfil["gasto_mensual"])),
        "ratio_endeudamiento": Decimal(str(perfil["ratio_endeudamiento"])),
        "fondo_emergencia_meses": Decimal(str(perfil["fondo_emergencia_usd"]))
        / Decimal(str(perfil["gasto_mensual"])),
    }
    detalle = {
        "record_id": record_id,
        "meta_ahorro_mensual": Decimal(str(perfil["meta_ahorro_mensual"])),
        "ahorro_del_mes": Decimal(str(ahorro)),
        "meta_ahorro_cumplida": perfil["meta_cumplida"],
        "inversion_mensual": Decimal(str(perfil["inversion_mensual"])),
        "fondo_emergencia_usd": Decimal(str(perfil["fondo_emergencia_usd"])),
    }
    return comportamiento, detalle


class TestNivel(unittest.TestCase):
    def test_las_dos_anas(self):
        self.assertEqual(ana_primeriza().ratio_endeudamiento, 0.58)
        self.assertEqual(pe.calcular_nivel(0.58, ana_primeriza().fondo_meses), 1)
        self.assertEqual(pe.calcular_nivel(0.17, ana_madura().fondo_meses), 2)

    def test_umbral_de_endeudamiento_es_estricto(self):
        # "> 0.40" => exactamente 0.40 todavía es manejable (igual que el CASE del SQL).
        self.assertEqual(pe.calcular_nivel(0.40, 0.5), 2)
        self.assertEqual(pe.calcular_nivel(0.41, 0.5), 1)

    def test_umbral_de_colchon_es_inclusivo(self):
        # "< 3" => exactamente 3.0 meses ya es nivel 3.
        self.assertEqual(pe.calcular_nivel(0.20, 2.99), 2)
        self.assertEqual(pe.calcular_nivel(0.20, 3.0), 3)

    def test_deuda_alta_gana_aunque_haya_colchon(self):
        self.assertEqual(pe.calcular_nivel(0.55, 5.0), 1)


class TestPerfil(unittest.TestCase):
    def test_ahorro_del_mes_con_piso_en_cero(self):
        self.assertAlmostEqual(ana_primeriza().ahorro_mes, 626.83, places=2)
        deficit = pe.PerfilFinanciero(**{**ANA_PRIMERIZA, "gasto_mensual": 4000.0})
        self.assertEqual(deficit.ahorro_mes, 0.0)

    def test_progreso_y_falta_de_la_meta(self):
        a, b = ana_primeriza(), ana_madura()
        self.assertAlmostEqual(a.progreso_meta, 0.2857, places=4)
        self.assertAlmostEqual(b.progreso_meta, 0.6014, places=4)
        self.assertAlmostEqual(a.falta_meta_mensual, 1567.22, places=2)
        self.assertAlmostEqual(b.falta_meta_mensual, 935.53, places=2)

    def test_fondo_en_meses(self):
        # 540.88 / 3077.46 = 0.1758 (unos 5 días); 1286.49 / 2443.44 = 0.5265
        self.assertAlmostEqual(ana_primeriza().fondo_meses, 540.88 / 3077.46, places=9)
        self.assertAlmostEqual(ana_madura().fondo_meses, 1286.49 / 2443.44, places=9)
        self.assertAlmostEqual(ana_primeriza().fondo_meses, 0.1758, places=3)
        self.assertAlmostEqual(ana_madura().fondo_meses, 0.5265, places=3)

    def test_validaciones(self):
        with self.assertRaises(ValueError):
            pe.PerfilFinanciero(**{**ANA_MADURA, "ingreso_mensual": 0.0})
        with self.assertRaises(ValueError):
            pe.PerfilFinanciero(**{**ANA_MADURA, "gasto_mensual": -1.0})


class TestColchon(unittest.TestCase):
    def test_brecha_de_las_dos_anas(self):
        a = pe.plan_colchon(ana_primeriza())
        b = pe.plan_colchon(ana_madura())
        self.assertAlmostEqual(a.monto_objetivo, 9232.38, places=2)
        self.assertAlmostEqual(a.brecha, 8691.50, places=2)
        self.assertAlmostEqual(b.monto_objetivo, 7330.32, places=2)
        self.assertAlmostEqual(b.brecha, 6043.83, places=2)

    def test_meses_estimados_redondean_hacia_arriba(self):
        # 8691.50 / 626.83 = 13.87 -> 14; 6043.83 / 1411.45 = 4.28 -> 5
        self.assertEqual(pe.plan_colchon(ana_primeriza()).meses_estimados, 14)
        self.assertEqual(pe.plan_colchon(ana_madura()).meses_estimados, 5)

    def test_multiplo_exacto_no_suma_un_mes_por_ruido(self):
        p = pe.PerfilFinanciero(**{**ANA_MADURA, "fondo_emergencia_usd": 0.0})
        plan = pe.plan_colchon(p, aporte_mensual=p.gasto_mensual * 3 / 4)
        self.assertEqual(plan.meses_estimados, 4)

    def test_sin_ahorro_no_hay_plazo(self):
        plan = pe.plan_colchon(ana_madura(), aporte_mensual=0.0)
        self.assertIsNone(plan.meses_estimados)
        self.assertFalse(plan.cumplido)

    def test_colchon_ya_cubierto(self):
        p = pe.PerfilFinanciero(**{**ANA_MADURA, "fondo_emergencia_usd": 3 * 2443.44})
        plan = pe.plan_colchon(p)
        self.assertEqual(plan.brecha, 0.0)
        self.assertEqual(plan.meses_estimados, 0)
        self.assertTrue(plan.cumplido)

    def test_aporte_negativo_se_rechaza(self):
        with self.assertRaises(ValueError):
            pe.plan_colchon(ana_madura(), aporte_mensual=-1.0)


class TestRetiro(unittest.TestCase):
    @staticmethod
    def simulacion_mes_a_mes(aportacion, anios, rendimiento_real, saldo_inicial=0.0):
        """Referencia independiente: crece el saldo un mes y luego entra la aportación."""
        tasa_mensual = (1 + rendimiento_real) ** (1 / 12) - 1
        saldo = saldo_inicial
        for _ in range(anios * 12):
            saldo = saldo * (1 + tasa_mensual) + aportacion
        return saldo

    def test_coincide_con_la_simulacion_mes_a_mes(self):
        for aportacion, anios, rend, inicial in [
            (100.0, 30, 0.06, 0.0),
            (140.81, 30, 0.06, 0.0),
            (202.27, 25, 0.04, 500.0),
            (50.0, 10, 0.02, 0.0),
            (300.0, 40, 0.06, 1000.0),
        ]:
            r = pe.proyectar_retiro(
                pe.SupuestosRetiro(aportacion, anios, rend, inicial)
            )
            esperado = self.simulacion_mes_a_mes(aportacion, anios, rend, inicial)
            self.assertAlmostEqual(
                r.saldo_final, esperado, places=4, msg=(aportacion, anios, rend)
            )

    def test_defaults_son_30_anios_y_6_por_ciento_real(self):
        r = pe.proyectar_retiro(pe.SupuestosRetiro(aportacion_mensual=100.0))
        self.assertEqual(r.supuestos.anios, 30)
        self.assertEqual(r.supuestos.rendimiento_anual_real, 0.06)
        self.assertAlmostEqual(
            r.saldo_final, self.simulacion_mes_a_mes(100.0, 30, 0.06), places=4
        )

    def test_el_saldo_crece_exactamente_el_rendimiento_anual(self):
        # Con saldo inicial y SIN aportaciones, un año deja exactamente +6%.
        r = pe.proyectar_retiro(pe.SupuestosRetiro(0.0, 10, 0.06, 1000.0))
        self.assertAlmostEqual(r.saldo_final, 1000.0 * 1.06**10, places=6)

    def test_rendimiento_cero_es_solo_acumular(self):
        r = pe.proyectar_retiro(pe.SupuestosRetiro(100.0, 30, 0.0))
        self.assertAlmostEqual(r.saldo_final, 36000.0, places=6)
        self.assertAlmostEqual(r.rendimiento_estimado, 0.0, places=6)

    def test_desglose_cuadra(self):
        r = pe.proyectar_retiro(pe.SupuestosRetiro(140.81, 30, 0.06, 250.0))
        self.assertAlmostEqual(r.total_aportado, 140.81 * 360, places=6)
        self.assertAlmostEqual(
            r.saldo_final,
            r.supuestos.saldo_inicial + r.total_aportado + r.rendimiento_estimado,
            places=6,
        )

    def test_plazo_fuera_de_rango_o_no_entero_se_rechaza(self):
        for anios in (9, 41, 0, 30.5):
            with self.assertRaises(ValueError, msg=anios):
                pe.proyectar_retiro(pe.SupuestosRetiro(100.0, anios))
        pe.proyectar_retiro(pe.SupuestosRetiro(100.0, 10))  # extremos válidos
        pe.proyectar_retiro(pe.SupuestosRetiro(100.0, 40))

    def test_valores_negativos_se_rechazan(self):
        with self.assertRaises(ValueError):
            pe.proyectar_retiro(pe.SupuestosRetiro(-1.0))
        with self.assertRaises(ValueError):
            pe.proyectar_retiro(pe.SupuestosRetiro(100.0, saldo_inicial=-1.0))
        with self.assertRaises(ValueError):
            pe.proyectar_retiro(pe.SupuestosRetiro(100.0, rendimiento_anual_real=-1.0))


class TestPlanCompleto(unittest.TestCase):
    def test_ana_primeriza(self):
        plan = pe.generar_plan(ana_primeriza())
        self.assertEqual((plan.nivel, plan.nombre_nivel), (1, "Primeros pasos"))
        self.assertAlmostEqual(plan.falta_meta_mensual, 1567.22, places=2)
        self.assertAlmostEqual(plan.colchon.brecha, 8691.50, places=2)
        self.assertAlmostEqual(plan.de_cada_100_a_deuda, 58.0, places=6)
        self.assertAlmostEqual(plan.brecha_deuda_mensual, 0.18 * 3704.29, places=2)
        self.assertIsNone(
            plan.aporte_paralelo_referencia
        )  # nivel 1: sin inversión en paralelo
        self.assertEqual(plan.productos, ("cuenta de ahorro", "ahorro programado"))
        self.assertFalse(plan.meta_cumplida)

    def test_ana_madura(self):
        plan = pe.generar_plan(ana_madura())
        self.assertEqual((plan.nivel, plan.nombre_nivel), (2, "Construyendo base"))
        self.assertAlmostEqual(plan.falta_meta_mensual, 935.53, places=2)
        self.assertAlmostEqual(plan.colchon.brecha, 6043.83, places=2)
        self.assertEqual(plan.brecha_deuda_mensual, 0.0)
        # S2: en nivel 2 la referencia "en paralelo" es lo que ya aporta, y sale del ahorro del mes.
        self.assertAlmostEqual(plan.aporte_paralelo_referencia, 202.27, places=2)
        self.assertAlmostEqual(plan.colchon.aporte_mensual, 1411.45 - 202.27, places=2)
        self.assertEqual(
            plan.colchon.meses_estimados, 5
        )  # 6043.83 / 1209.18 = 4.998 -> 5
        self.assertEqual(
            plan.productos,
            ("ahorro programado", "inversión de bajo riesgo", "ahorro para el retiro"),
        )

    def test_nivel_2_sin_inversion_actual_no_inventa_un_monto(self):
        p = pe.PerfilFinanciero(**{**ANA_MADURA, "inversion_mensual": 0.0})
        self.assertIsNone(pe.generar_plan(p).aporte_paralelo_referencia)

    def test_nivel_3_y_sus_productos(self):
        p = pe.PerfilFinanciero(**{**ANA_MADURA, "fondo_emergencia_usd": 3.5 * 2443.44})
        plan = pe.generar_plan(p)
        self.assertEqual(plan.nivel, 3)
        self.assertEqual(
            plan.productos, ("inversión de bajo riesgo", "ahorro para el retiro")
        )
        self.assertTrue(plan.colchon.cumplido)

    def test_meta_cumplida_viene_del_perfil(self):
        p = pe.PerfilFinanciero(**{**ANA_MADURA, "meta_cumplida": True})
        self.assertTrue(pe.generar_plan(p).meta_cumplida)


class TestRoadmap(unittest.TestCase):
    def test_orden_y_peldanos_de_ana_madura(self):
        pasos = pe.construir_roadmap(ana_madura())
        self.assertEqual(
            [p.clave for p in pasos], ["colchon_3_meses", "colchon_6_meses", "retiro"]
        )
        self.assertEqual([p.orden for p in pasos], [1, 2, 3])
        self.assertAlmostEqual(pasos[0].brecha, 6043.83, places=2)
        self.assertAlmostEqual(pasos[1].brecha, 6 * 2443.44 - 1286.49, places=2)
        self.assertFalse(any(p.cumplido for p in pasos))
        self.assertIsNone(
            pasos[2].monto_objetivo
        )  # el retiro es abierto: nunca "cumplido"

    def test_con_6_meses_cubiertos_solo_queda_el_retiro(self):
        p = pe.PerfilFinanciero(**{**ANA_MADURA, "fondo_emergencia_usd": 6.2 * 2443.44})
        pasos = pe.construir_roadmap(p)
        self.assertTrue(pasos[0].cumplido and pasos[1].cumplido)
        self.assertFalse(pasos[2].cumplido)

    def test_con_3_meses_cubiertos_falta_el_de_6(self):
        p = pe.PerfilFinanciero(**{**ANA_MADURA, "fondo_emergencia_usd": 4.0 * 2443.44})
        pasos = pe.construir_roadmap(p)
        self.assertTrue(pasos[0].cumplido)
        self.assertFalse(pasos[1].cumplido)
        self.assertAlmostEqual(pasos[1].brecha, 2.0 * 2443.44, places=2)


class TestTextoParaElPrompt(unittest.TestCase):
    def test_ana_primeriza_dice_las_cifras_del_documento(self):
        texto = pe.contexto_plan_para_prompt(pe.generar_plan(ana_primeriza()))
        for esperado in (
            "Nivel: 1 (Primeros pasos)",
            "$1,567",  # falta al mes para su meta de ahorro
            "$8,692",  # falta para 3 meses de colchón
            "de cada $100 que ganas, $58",
            "lo manejable es hasta $40 de cada $100",
            "unos 5 días",  # 0.18 meses
        ):
            self.assertIn(esperado, texto)

    def test_no_dice_un_monto_de_deuda_en_usd_derivado_del_ratio(self):
        # t077 v2.3 §7: de la deuda solo se muestra el ratio. $667 = (0.58 - 0.40) x ingreso.
        texto = pe.contexto_plan_para_prompt(pe.generar_plan(ana_primeriza()))
        self.assertNotIn("$667", texto)
        self.assertNotIn("bajar", texto)

    def test_ana_madura_dice_las_cifras_del_documento(self):
        texto = pe.contexto_plan_para_prompt(pe.generar_plan(ana_madura()))
        for esperado in (
            "Nivel: 2 (Construyendo base)",
            "$936",
            "$6,044",
            "de cada $100 que ganas, $17",
            "ya aportas",
        ):
            self.assertIn(esperado, texto)

    def test_texto_de_retiro_marca_el_supuesto(self):
        r = pe.proyectar_retiro(pe.SupuestosRetiro(aportacion_mensual=202.27))
        texto = pe.contexto_retiro_para_prompt(r)
        for esperado in (
            "estimado ilustrativo",
            "6.0% anual real",
            "30 años",
            "no es un dato ni una promesa",
        ):
            self.assertIn(esperado, texto)


class TestDesdeFilas(unittest.TestCase):
    def test_arma_el_perfil_de_filas_con_decimal(self):
        comp, det = filas_gold("PFT_0000636", ANA_PRIMERIZA, ahorro=626.83)
        perfil = pe.PerfilFinanciero.desde_filas(comp, det)
        self.assertEqual(perfil.record_id, "PFT_0000636")
        self.assertAlmostEqual(perfil.ahorro_mes, 626.83, places=2)
        self.assertEqual(pe.generar_plan(perfil).nivel, 1)

    def test_record_id_desalineados_se_rechazan(self):
        comp, det = filas_gold("PFT_0000636", ANA_PRIMERIZA, ahorro=626.83)
        det["record_id"] = "PFT_0002539"
        with self.assertRaises(pe.PerfilIncoherenteError):
            pe.PerfilFinanciero.desde_filas(comp, det)

    def test_ahorro_que_no_cuadra_con_ingreso_menos_gasto_se_rechaza(self):
        # Simula que el detalle describe a otra persona (record_id desalineado en Gold).
        comp, det = filas_gold("PFT_0000636", ANA_PRIMERIZA, ahorro=1411.45)
        with self.assertRaises(pe.PerfilIncoherenteError):
            pe.PerfilFinanciero.desde_filas(comp, det)

    def test_fondo_que_no_cuadra_se_rechaza(self):
        comp, det = filas_gold("PFT_0000636", ANA_PRIMERIZA, ahorro=626.83)
        det["fondo_emergencia_usd"] = Decimal("1286.49")
        with self.assertRaises(pe.PerfilIncoherenteError):
            pe.PerfilFinanciero.desde_filas(comp, det)

    def test_bandera_de_meta_que_contradice_se_rechaza(self):
        comp, det = filas_gold("PFT_0000636", ANA_PRIMERIZA, ahorro=626.83)
        det["meta_ahorro_cumplida"] = True
        with self.assertRaises(pe.PerfilIncoherenteError):
            pe.PerfilFinanciero.desde_filas(comp, det)

    def test_ahorro_con_piso_en_cero_es_coherente(self):
        deficit = {**ANA_PRIMERIZA, "gasto_mensual": 4000.0}
        comp, det = filas_gold("PFT_0000636", deficit, ahorro=0.0)
        perfil = pe.PerfilFinanciero.desde_filas(comp, det)
        self.assertEqual(perfil.ahorro_mes, 0.0)


class TestConsistenciaConElSimulador(unittest.TestCase):
    """plan_engine NO importa `escenario_empleo_demo` (arrastraría numpy,
    scipy, pandas y psycopg2 por una fórmula de una línea). Esta prueba
    vigila que ambas definiciones del colchón sigan siendo la misma."""

    def test_misma_brecha_y_mismo_benchmark_que_t070(self):
        try:
            import escenario_empleo_demo as t070
        except ImportError as exc:  # fuera del contenedor de Streamlit
            self.skipTest(f"no se pudo importar escenario_empleo_demo: {exc}")
        self.assertEqual(t070.BENCHMARK_MESES_FONDO_EMERGENCIA, pe.MESES_COLCHON_MINIMO)
        for datos in (ANA_PRIMERIZA, ANA_MADURA):
            perfil = pe.PerfilFinanciero(**datos)
            esperado = t070.monto_meta_escenario_empleo(
                perfil.fondo_meses, perfil.gasto_mensual
            )
            self.assertAlmostEqual(pe.plan_colchon(perfil).brecha, esperado, places=6)
        # Y el caso "ya cubre el benchmark": ambos dan 0, no un monto negativo.
        rico = pe.PerfilFinanciero(
            **{**ANA_MADURA, "fondo_emergencia_usd": 5 * 2443.44}
        )
        self.assertEqual(pe.plan_colchon(rico).brecha, 0.0)
        self.assertEqual(
            t070.monto_meta_escenario_empleo(rico.fondo_meses, rico.gasto_mensual), 0.0
        )


if __name__ == "__main__":
    unittest.main()
