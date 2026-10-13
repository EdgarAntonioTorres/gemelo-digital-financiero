"""
Pruebas de `assistant/contexto_centavo.py` y de las partes puras de
`assistant/router.py` y `assistant/text_to_sql.py` (paso 2, Sesión 36).

Sin Ollama, sin Postgres, sin Streamlit: solo `unittest`. Mismo comando
que `test_plan_engine.py`:

    docker compose run --rm --no-deps streamlit python -m unittest discover -s tests -v

Los valores esperados salen del handoff/bitácora de la Sesión 36 (las dos
Anas con `plan_engine`): no son números inventados para que la prueba pase.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from assistant import contexto_centavo as ctx
from assistant import plan_engine as pe
from assistant import consulta_grupo, router, text_to_sql

REGLA_PROHIBIDA = (
    "cash_flow_status",
    "savings_rate",
    "financial_stress_level",
    "financial_advice_score",
    "loan_payment",
)


def _cargado(ingreso, gasto, ratio, fondo_usd, meta, inversion, rid, irfi=0.5, ica=0.3):
    perfil = pe.PerfilFinanciero(
        ingreso, gasto, ratio, fondo_usd, meta, False, inversion, rid
    )
    return SimpleNamespace(
        record_id=rid,
        perfil=perfil,
        plan=pe.generar_plan(perfil),
        comportamiento={"income_type": "Freelance"},
        detalle={"suscripciones_activas": 3, "proporcion_esencial": 0.7936},
        irfi=irfi,
        ica=ica,
    )


def ana_primeriza():
    return _cargado(3704.29, 3077.46, 0.58, 540.88, 2194.05, 140.81, "PFT_0000636")


def ana_madura():
    return _cargado(3854.89, 2443.44, 0.17, 1286.49, 2346.98, 202.27, "PFT_0002539")


class TestContextoPerfil(unittest.TestCase):
    def test_cifras_en_dolares_enteros(self):
        t = ctx.contexto_perfil(ana_primeriza(), "Ana")
        self.assertIn("Ingreso mensual: $3,704.", t)
        self.assertIn("Ahorro del mes: $627 (17% del ingreso)", t)
        self.assertNotIn("626.83", t)
        self.assertIn("de cada $100 que gana, $58 van a pagar deudas", t)

    def test_nivel_y_nombre(self):
        self.assertIn(
            "Nivel de madurez financiera: 1 (Primeros pasos)",
            ctx.contexto_perfil(ana_primeriza(), "Ana"),
        )
        self.assertIn("2 (Construyendo base)", ctx.contexto_perfil(ana_madura(), "Ana"))
        self.assertIn(
            "Nombre de la persona: Ana.", ctx.contexto_perfil(ana_madura(), "Ana")
        )
        self.assertNotIn("Nombre de la persona", ctx.contexto_perfil(ana_madura()))

    def test_no_incluye_campos_prohibidos(self):
        t = ctx.contexto_perfil(ana_primeriza(), "Ana")
        for campo in REGLA_PROHIBIDA:
            self.assertNotIn(campo, t)

    def test_gasto_mayor_que_ingreso_no_regaña_y_es_honesto(self):
        c = _cargado(1000, 1200, 0.2, 100, 300, 0, "X")
        t = ctx.contexto_perfil(c)
        self.assertIn("Gasta $200 más de lo que gana; ahorro del mes: $0.", t)

    def test_sin_irfi_ica_no_los_menciona(self):
        c = ana_primeriza()
        c.irfi = c.ica = None
        t = ctx.contexto_perfil(c)
        self.assertNotIn("IRFI", t)
        self.assertNotIn("ICA", t)


class TestBloquesPorCategoria(unittest.TestCase):
    def test_perfil_trae_cifras_de_plan_engine(self):
        t = ctx.bloque_de_codigo("PERFIL", ana_primeriza(), "¿cómo voy?")
        self.assertIn("te faltan $8,692", t)  # colchón de 3 meses, Ana primeriza
        self.assertIn("unos 14 meses", t)

    def test_plan_sin_retiro_no_incluye_proyeccion(self):
        t = ctx.bloque_de_codigo("PLAN", ana_madura(), "¿cuánto me falta para 3 meses?")
        self.assertNotIn("PROYECCIÓN DE RETIRO", t)
        self.assertIn("te faltan $6,044", t)

    def test_plan_retiro_con_monto_de_la_pregunta(self):
        t = ctx.bloque_de_codigo(
            "PLAN",
            ana_madura(),
            "¿Cuánto tendría para el retiro si aporto $200 al mes?",
        )
        self.assertIn("PROYECCIÓN DE RETIRO", t)
        self.assertIn("$200 al mes durante 30 años", t)
        self.assertIn("6.0% anual real", t)
        self.assertIn("la cantidad que mencionó la persona", t)

    def test_retiro_usa_la_inversion_actual_si_no_dice_monto(self):
        t = ctx.bloque_de_codigo(
            "PLAN", ana_madura(), "¿Cuánto tendría para mi retiro?"
        )
        self.assertIn("lo que la persona ya aporta hoy", t)
        self.assertIn("$202 al mes", t)
        self.assertIn("$197,115", t)  # cifra de la bitácora para Ana madura

    def test_retiro_sin_monto_ni_inversion_no_inventa(self):
        c = _cargado(3000, 2000, 0.2, 500, 900, 0.0, "Y")
        t = ctx.bloque_de_codigo("PLAN", c, "¿Cuánto tendría para el retiro?")
        self.assertIn("NO inventes un monto", t)
        self.assertNotIn("PROYECCIÓN DE RETIRO (estimado", t)

    def test_porcentaje_no_se_toma_como_aportacion(self):
        s, _ = ctx.extraer_supuestos_retiro(
            "¿y si ahorro 10% más para el retiro?", 140.81
        )
        self.assertEqual(s.aportacion_mensual, 140.81)

    def test_anios_en_rango_y_fuera_de_rango(self):
        s, _ = ctx.extraer_supuestos_retiro("si aporto 300 al mes por 25 años", 0)
        self.assertEqual((s.aportacion_mensual, s.anios), (300.0, 25))
        s, notas = ctx.extraer_supuestos_retiro("si aporto 300 al mes por 60 años", 0)
        self.assertEqual(s.anios, pe.RETIRO_ANIOS_DEFAULT)
        self.assertTrue(any("60 años" in n for n in notas))

    def test_monto_con_comas(self):
        s, _ = ctx.extraer_supuestos_retiro("si aporto $1,250.50 al mes", 0)
        self.assertEqual(s.aportacion_mensual, 1250.50)

    def test_producto_nivel_1_solo_ahorro_y_sin_inversion(self):
        t = ctx.bloque_de_codigo("PRODUCTO", ana_primeriza(), "¿qué me conviene?")
        self.assertIn("cuenta de ahorro", t)
        self.assertIn("ahorro programado", t)
        self.assertIn("NO recomiendes inversión ni retiro", t)
        self.assertNotIn("inversión de bajo riesgo (", t)
        self.assertNotIn("PROYECCIÓN DE RETIRO", t)

    def test_producto_nivel_2_en_paralelo_con_referencia(self):
        t = ctx.bloque_de_codigo("PRODUCTO", ana_madura(), "¿qué me conviene?")
        self.assertIn("ahorro programado (prioridad: el colchón)", t)
        self.assertIn("inversión de bajo riesgo (en paralelo", t)
        self.assertIn("ahorro para el retiro (en paralelo", t)
        self.assertIn("$202 al mes, que es lo que ya aporta", t)
        self.assertIn("PROYECCIÓN DE RETIRO", t)

    def test_producto_nivel_2_sin_inversion_no_inventa_monto(self):
        c = _cargado(3000, 2400, 0.2, 500, 900, 0.0, "Z")  # nivel 2, inversión $0
        t = ctx.bloque_de_codigo("PRODUCTO", c, "¿qué me conviene?")
        self.assertIn("NO inventes uno", t)

    def test_producto_sin_catalogo_extra_ni_credito(self):
        for c in (ana_primeriza(), ana_madura()):
            t = ctx.bloque_de_codigo("PRODUCTO", c, "x").lower()
            self.assertIn("no recomiendes crédito", t)
            for ajeno in ("tarjeta de crédito", "préstamo", "criptomoneda", "acciones"):
                self.assertNotIn(ajeno, t)

    def test_roadmap_no_cumplida_se_presenta_como_lo_que_viene(self):
        t = ctx.bloque_de_codigo("ROADMAP", ana_madura(), "¿qué sigue?")
        self.assertIn("todavía NO cumplida", t)
        self.assertIn("lo que viene", t)
        self.assertIn("Colchón de 6 meses de gastos", t)

    def test_roadmap_meta_cumplida(self):
        c = ana_madura()
        perfil = pe.PerfilFinanciero(
            3854.89, 2443.44, 0.17, 1286.49, 1000.0, True, 202.27, "R"
        )
        c.perfil, c.plan = perfil, pe.generar_plan(perfil)
        t = ctx.bloque_de_codigo("ROADMAP", c, "¿qué sigue?")
        self.assertIn("CUMPLIDA", t)

    def test_categoria_sin_codigo_falla(self):
        with self.assertRaises(ValueError):
            ctx.bloque_de_codigo("DATOS", ana_madura(), "x")


class TestPreguntasSugeridas(unittest.TestCase):
    def test_nivel_1(self):
        q = ctx.preguntas_sugeridas(ana_primeriza())
        self.assertIn("¿Qué tan pesada es mi deuda?", q)
        self.assertNotIn("retiro", " ".join(q).lower())

    def test_nivel_2_con_monto_real(self):
        q = ctx.preguntas_sugeridas(ana_madura())
        self.assertIn("¿Cuánto tendría para el retiro si aporto $202 al mes?", q)
        self.assertIn("¿Cuánto me falta para tener 3 meses cubiertos?", q)

    def test_comunes_al_final(self):
        for c in (ana_primeriza(), ana_madura()):
            self.assertEqual(
                ctx.preguntas_sugeridas(c)[-2:],
                ["¿Cuánto me queda cada mes?", "¿Cómo voy con mi meta de ahorro?"],
            )


class TestParseoDeCategoria(unittest.TestCase):
    def test_acentos(self):
        self.assertEqual(router.parsear_categoria("SIMULACIÓN"), "SIMULACION")

    def test_fuera_de_tema_con_espacios_y_minusculas(self):
        self.assertEqual(router.parsear_categoria("fuera de tema"), "FUERA_DE_TEMA")

    def test_toma_la_primera(self):
        self.assertEqual(
            router.parsear_categoria("PLAN, aunque también podría ser PERFIL"), "PLAN"
        )
        self.assertEqual(
            router.parsear_categoria("Creo que es PERFIL (no PLAN)"), "PERFIL"
        )

    def test_irreconocible_cae_en_el_fallback(self):
        self.assertEqual(router.parsear_categoria("no sé"), router.CATEGORIA_FALLBACK)

    def test_las_8_categorias(self):
        for c in router.CATEGORIAS_VALIDAS:
            self.assertEqual(router.parsear_categoria(c), c)


class TestPromptDeSistema(unittest.TestCase):
    def test_se_puede_formatear_y_sin_llaves_sueltas(self):
        t = router.SYSTEM_PROMPT_TEMPLATE.format(
            nombre_txt="",
            contexto_perfil="a",
            resultado_consulta="b",
            fragmentos_rag="c",
        )
        self.assertNotIn("{", t)

    def test_reglas_clave_presentes(self):
        t = router.SYSTEM_PROMPT_TEMPLATE
        for frase in (
            "6.0% anual real",
            "NUNCA lo atribuyas a un producto",
            "catálogo cerrado",
            'nunca digas que la persona "mejoró"',
            'Nunca digas "no calificas"',
        ):
            self.assertIn(frase, t)

    def test_ya_no_prohibe_recomendar_tipos_de_producto(self):
        self.assertNotIn(
            "no recomiendas productos", router.SYSTEM_PROMPT_TEMPLATE.lower()
        )


class TestArreglosPrimeraCorridaReal(unittest.TestCase):
    """Un caso por cada hallazgo de la primera corrida con Ollama (Sesión 36)."""

    def test_prompt_no_trae_cifras_de_nadie_que_puedan_filtrarse(self):
        """Ninguna cifra de las dos Anas (ni de los ejemplos viejos) puede
        estar en la plantilla: el modelo de 8B las copia a respuestas de
        otra persona (visto en la primera corrida real)."""
        import re

        prohibidas = (
            "627",
            "3,704",
            "3,077",
            "2,952",
            "2,846",
            "1,412",
            "1,411",
            "541",
            "8,692",
            "6,044",
            "0.58",
            "0.17",
            "626.83",
        )
        t = router.SYSTEM_PROMPT_TEMPLATE
        for cifra in prohibidas:
            self.assertNotIn(cifra, t)
        # $58 y $17 (deuda por cada $100 de cada Ana), como palabra completa
        self.assertIsNone(re.search(r"\$(58|17)\b", t))

    def test_prompt_pide_usar_ahorro_del_mes_y_corregir_premisas(self):
        t = router.SYSTEM_PROMPT_TEMPLATE
        self.assertIn("no restes tú el ingreso y el gasto", t)
        self.assertIn("da por hecho algo que los datos no confirman", t)

    def test_clasificador_distingue_situacion_propia_de_concepto(self):
        self.assertIn("situación PROPIA", router.CLASIFICACION_PROMPT)
        self.assertIn("NO es CONCEPTOS", router.CLASIFICACION_PROMPT)

    def test_roadmap_declara_que_el_colchon_no_esta_completo(self):
        t = ctx.bloque_de_codigo(
            "ROADMAP", ana_madura(), "¿qué sigue después de mi colchón?"
        )
        self.assertIn("todavía NO está completo", t)
        self.assertIn("NO digas que ya lo tiene", t)
        self.assertIn("$6,044", t)

    def test_roadmap_colchon_completo(self):
        c = _cargado(3000, 1000, 0.1, 3500, 500, 100, "W")  # fondo = 3.5 meses
        t = ctx.bloque_de_codigo("ROADMAP", c, "¿qué sigue?")
        self.assertIn("ya está completo", t)

    def test_respuesta_sin_simulacion_es_fija_y_util(self):
        con = router.respuesta_sin_simulacion("Ana")
        sin = router.respuesta_sin_simulacion()
        self.assertTrue(con.startswith("Ana, todavía"))
        self.assertTrue(sin.startswith("Todavía"))
        for r in (con, sin):
            self.assertIn("Simulador", r)
            self.assertNotIn("$", r)  # no puede citar cifras


class TestArreglosSegundaCorridaReal(unittest.TestCase):
    """Un caso por cada hallazgo de la segunda corrida con Ollama (Sesión 36)."""

    # --- precedencia de SIMULACION -------------------------------------------
    def test_pregunta_de_simulacion_se_detecta_por_palabras_clave(self):
        for q in (
            "¿Qué significa mi probabilidad de llegar a la meta?",
            '¿Qué es el "intervalo de confianza" que mencionas?',
            "¿Qué significa que tenga esa probabilidad de llegar a mi meta?",
            "Explícame mi simulación",
            "¿Qué quiere decir IC 95%?",
        ):
            self.assertTrue(router.es_pregunta_de_simulacion(q), q)

    def test_no_se_fuerza_simulacion_en_otras_preguntas(self):
        for q in (
            "¿Qué es un fondo de emergencia?",
            "¿Cuánto me queda cada mes?",
            "¿Cuál es la probabilidad de que me aprueben un crédito?",
            "¿Qué probabilidad tengo de ganar con acciones?",
            "¿Me van a aprobar un préstamo?",
        ):
            self.assertFalse(router.es_pregunta_de_simulacion(q), q)

    # --- bloque de SIMULACION ---------------------------------------------------
    def test_bloque_simulacion_explica_bien_el_ic(self):
        t = ctx.bloque_simulacion(
            "Escenario: X. Probabilidad de éxito: 68.1% (IC 95%: [67.2%, 69.0%])."
        )
        self.assertIn("68.1%", t)
        self.assertIn("qué tan estable", t)
        self.assertIn("NO significa 'una posibilidad en 20", t)

    # --- lecturas decididas por código ----------------------------------------
    def test_deuda_baja_se_declara_dentro_de_lo_manejable(self):
        t = ctx.contexto_perfil(ana_madura())
        self.assertIn("DENTRO de lo manejable: no la describas como alta", t)
        self.assertNotIn("POR ENCIMA de lo manejable", t)

    def test_deuda_alta_se_declara_por_encima(self):
        t = ctx.contexto_perfil(ana_primeriza())
        self.assertIn("POR ENCIMA de lo manejable", t)

    def test_fondo_corto_dice_que_no_llega_a_3_meses(self):
        self.assertIn("Todavía no llega a 3 meses", ctx.contexto_perfil(ana_madura()))
        c = _cargado(3000, 1000, 0.1, 3500, 500, 100, "W")
        self.assertIn("Ya cubre 3 meses o más", ctx.contexto_perfil(c))

    def test_roadmap_distingue_meta_mensual_de_colchon(self):
        t = ctx.bloque_de_codigo("ROADMAP", ana_primeriza(), "¿qué sigue?")
        self.assertIn("No confundas la 'meta de ahorro mensual'", t)

    def test_producto_nivel_1_no_afirma_que_el_colchon_esta_mezclado(self):
        t = ctx.bloque_de_codigo("PRODUCTO", ana_primeriza(), "¿qué me conviene?")
        self.assertIn("no afirmes que hoy lo tiene mezclado", t)

    # --- consulta_grupo: función pura + consulta fija con BD simulada ----------
    GRUPO = {
        "n": 1021,
        "ingreso": 3500.0,
        "gasto": 2800.0,
        "ahorro": 800.0,
        "ratio": 0.30,
        "fondo_meses": 0.40,
        "irfi": 0.45,
        "ica": 0.40,
        "alerta_fraude": False,
    }

    def test_lectura_la_decide_el_codigo(self):
        self.assertEqual(consulta_grupo.lectura(3704, 3500), "por encima del promedio")
        self.assertEqual(consulta_grupo.lectura(3000, 3500), "por debajo del promedio")
        self.assertEqual(consulta_grupo.lectura(3510, 3500), "parecido al promedio")
        self.assertEqual(consulta_grupo.lectura(5, None), "sin dato del grupo")

    def test_formatear_comparacion_trae_lecturas_y_no_inventa(self):
        t = consulta_grupo.formatear(ana_primeriza(), self.GRUPO)
        self.assertIn("1,021 personas", t)
        self.assertIn(
            "Ingreso mensual: tú $3,704; promedio del grupo $3,500 "
            "(por encima del promedio)",
            t,
        )
        self.assertIn("Deuda", t)
        self.assertIn("tú $58; promedio del grupo $30 (por encima del promedio)", t)
        self.assertIn("no hay ninguna alerta activa", t)
        self.assertIn("ni inventes porcentajes", t)

    def test_formatear_con_alerta_de_fraude_y_sin_datos(self):
        g = dict(self.GRUPO, alerta_fraude=True)
        self.assertIn(
            "SÍ hay una alerta activa", consulta_grupo.formatear(ana_madura(), g)
        )
        vacio = dict(self.GRUPO, n=0)
        self.assertIn(
            "no inventes promedios", consulta_grupo.formatear(ana_madura(), vacio)
        )

    def test_consultar_usa_consultas_parametrizadas_de_solo_lectura(self):
        ejecutadas = []

        class Cur:
            def __init__(self):
                self.i = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, q, params):
                ejecutadas.append((q, params))
                self.i += 1

            def fetchone(self):
                return [
                    (1021, 3500, 2800, 800, 0.3, 0.4),
                    (0.45, 0.40),
                    (False,),
                ][self.i - 1]

        class Conn:
            def cursor(self):
                return Cur()

        g = consulta_grupo.consultar(Conn(), "Freelance", "PFT_0000636")
        self.assertEqual(g["n"], 1021)
        self.assertIs(g["alerta_fraude"], False)
        self.assertEqual(
            [p for _, p in ejecutadas],
            [("Freelance",), ("Freelance",), ("PFT_0000636",)],
        )
        for q, _ in ejecutadas:
            self.assertTrue(q.strip().upper().startswith("SELECT"))
            self.assertNotIn("fact_perfil_detalle", q)  # nunca la tabla de 2 filas
            self.assertIn("%s", q)  # parametrizada, no f-string

    def test_el_router_ya_no_genera_sql_con_el_modelo(self):
        import inspect

        self.assertNotIn("text_to_sql.responder_pregunta", inspect.getsource(router))


class TestTerceraCorridaReal(unittest.TestCase):
    """Correcciones derivadas del informe t082 (62 respuestas)."""

    # --- reglas de clasificación (D22 y C16 reales) ---------------------------
    def test_que_banco_es_fuera_de_tema(self):
        self.assertEqual(
            router.clasificar_por_reglas("¿Qué banco me conviene?"), "FUERA_DE_TEMA"
        )
        self.assertEqual(
            router.clasificar_por_reglas("¿Cuál institución es mejor?"), "FUERA_DE_TEMA"
        )

    def test_meta_de_renta_va_a_conceptos(self):
        self.assertEqual(
            router.clasificar_por_reglas(
                "¿Por qué mi meta de renta es 2 veces mi gasto mensual?"
            ),
            "CONCEPTOS",
        )
        self.assertEqual(
            router.clasificar_por_reglas("¿Cómo se calcula el enganche del auto?"),
            "CONCEPTOS",
        )

    def test_reglas_no_atrapan_preguntas_normales(self):
        for q in (
            "¿Qué es una tarjeta de crédito?",
            "¿Cuánto me queda cada mes?",
            "¿Mi nivel de deuda respecto a mi ingreso es alto?",
            "¿Cuánto me falta para tener 3 meses cubiertos?",
            "¿Qué sigue después de mi colchón?",
        ):
            self.assertIsNone(router.clasificar_por_reglas(q), q)

    def test_precedencia_banco_antes_que_simulacion(self):
        self.assertEqual(
            router.clasificar_por_reglas(
                "¿Qué banco me da más probabilidad de aprobarme?"
            ),
            "FUERA_DE_TEMA",
        )

    # --- guardrail de cifras --------------------------------------------------
    CTX = "Te faltan $6,044. Objetivo $7,330. Ahorro $1,209. Pregunta del usuario."

    def test_guardrail_sin_cifras_raras_no_reintenta(self):
        llamadas = []
        r, info = router.aplicar_guardrail_cifras(
            "Te faltan $6,044 para llegar.",
            self.CTX,
            lambda n: llamadas.append(n) or "x",
        )
        self.assertEqual(r, "Te faltan $6,044 para llegar.")
        self.assertFalse(info["reintento"])
        self.assertEqual(llamadas, [])

    def test_guardrail_reintento_exitoso(self):  # real: "te falta $4,054"
        notas = []

        def regenerar(nota):
            notas.append(nota)
            return "Te faltan $6,044 para llegar a tus 3 meses."

        r, info = router.aplicar_guardrail_cifras(
            "Todavía no llegas, te falta $4,054.", self.CTX, regenerar
        )
        self.assertEqual(r, "Te faltan $6,044 para llegar a tus 3 meses.")
        self.assertTrue(info["reintento"])
        self.assertFalse(info["frases_quitadas"])
        self.assertEqual(info["cifras_primer_intento"], ["$4,054"])
        self.assertIn("$4,054", notas[0])
        self.assertIn("SOLO las cifras", notas[0])

    def test_guardrail_si_persiste_quita_solo_la_frase_mala(self):  # real: B8 "$2,156"
        mala = (
            "El ratio de endeudamiento es cuánto de tu ingreso se va en deudas. "
            "Si pagas $2,156 de deudas, tu ratio sería 58%. "
            "Un ratio bajo el 40% suele considerarse manejable."
        )
        r, info = router.aplicar_guardrail_cifras(mala, self.CTX, lambda n: mala)
        self.assertNotIn("$2,156", r)
        self.assertIn("El ratio de endeudamiento es", r)
        self.assertIn("suele considerarse manejable", r)
        self.assertTrue(info["frases_quitadas"])

    def test_guardrail_si_no_queda_nada_usa_el_mensaje_seguro(self):
        r, info = router.aplicar_guardrail_cifras(
            "Te falta $4,054.", self.CTX, lambda n: "Te falta $4,054."
        )
        self.assertEqual(r, router.MENSAJE_SIN_CIFRA_FIABLE)
        self.assertIn("Lo que tengo hoy", r)

    def test_guardrail_si_el_reintento_falla_sanea_el_primero(self):
        def boom(nota):
            raise RuntimeError("ollama caído")

        r, info = router.aplicar_guardrail_cifras(
            "Tienes un colchón bueno para empezar. Te falta $4,054.", self.CTX, boom
        )
        self.assertNotIn("$4,054", r)
        self.assertIn("error_reintento", info)

    def test_guardrail_ignora_porcentajes_derivados(self):
        r, info = router.aplicar_guardrail_cifras(
            "Es casi el 58% de lo que ganas, o sea $6,044.", self.CTX, lambda n: "x"
        )
        self.assertFalse(info["reintento"])

    # --- roadmap armado por código (E31 real: 2 de 2 respuestas sin la escalera) ---
    def test_roadmap_ana_madura_trae_orden_y_cifras_exactas(self):
        t = ctx.respuesta_roadmap(ana_madura(), "Ana")
        self.assertTrue(t.startswith("Ana, este es tu camino, un paso a la vez."))
        self.assertIn("Primero: colchón de 3 meses de gastos", t)
        self.assertIn("$7,330", t)
        self.assertIn("te faltan $6,044", t)
        self.assertIn("unos 5 meses", t)
        self.assertIn("Después: colchón de 6 meses de gastos", t)
        self.assertIn("retiro", t.lower())
        self.assertLess(t.index("Primero"), t.index("Después"))
        self.assertLess(t.index("Después"), t.lower().index("al final"))

    def test_roadmap_ana_primeriza(self):
        t = ctx.respuesta_roadmap(ana_primeriza(), "Ana")
        self.assertIn("te faltan $8,692", t)
        self.assertIn("unos 14 meses", t)

    def test_roadmap_no_dice_que_ya_tiene_el_colchon(self):
        t = ctx.respuesta_roadmap(ana_madura(), "Ana").lower()
        self.assertNotIn("ya tienes un colchón", t)

    def test_roadmap_con_colchon_completo_pasa_al_siguiente(self):
        c = _cargado(3000, 1000, 0.1, 3500, 500, 100, "W")  # 3.5 meses: el de 3 ya está
        t = ctx.respuesta_roadmap(c, "Ana")
        self.assertIn("Primero: colchón de 6 meses de gastos", t)

    def test_roadmap_sin_nombre(self):
        self.assertTrue(
            ctx.respuesta_roadmap(ana_madura()).startswith("Este es tu camino")
        )

    def test_las_cifras_del_roadmap_estan_respaldadas_por_el_plan(self):
        # cada monto en dólares del texto aparece en el bloque de plan_engine
        from assistant import verificaciones_respuesta as vr

        c = ana_madura()
        self.assertEqual(
            vr.cifras_sin_respaldo(
                ctx.respuesta_roadmap(c, "Ana"),
                ctx.bloque_de_codigo("PERFIL", c, "x"),
                solo_dolares=True,
            ),
            [],
        )

    def test_prompt_prohibe_umbrales_y_montos_de_pago_inventados(self):
        t = router.SYSTEM_PROMPT_TEMPLATE
        # Sesión 36 (mentor): IRFI/ICA/Salud SÍ tienen etiqueta oficial; lo que no se
        # puede es inventar otras. Antes el prompt decía "NO existen umbrales".
        self.assertIn("ETIQUETA OFICIAL", t)
        self.assertIn("no inventes montos de pago", t)
        self.assertIn("no es saludable", t)


class TestGuardrailDeTono(unittest.TestCase):
    """El guardrail ahora vigila también juicio y umbrales inventados."""

    CTX = (
        "Te faltan $6,044. De cada $100 que ganas, $58 van a pagar deudas. "
        "Lo manejable es hasta $40 de cada $100."
    )

    def test_juicio_se_reintenta_y_se_corrige(self):  # real: E24 primeriza
        notas = []

        def regenerar(nota):
            notas.append(nota)
            return (
                "De cada $100 que ganas, $58 van a pagar deudas. "
                "Lo manejable es hasta $40."
            )

        r, info = router.aplicar_guardrail(
            "Tu deuda es un problema, Ana. De cada $100 que ganas, $58 van a deudas.",
            self.CTX,
            regenerar,
        )
        self.assertNotIn("problema", r)
        self.assertTrue(info["reintento"])
        self.assertFalse(info["frases_quitadas"])
        self.assertEqual(
            info["frases_primer_intento"], ["Tu deuda es un problema, Ana."]
        )
        self.assertIn("Habla sin juzgar", notas[0])
        self.assertIn("nunca 'lo ideal'", notas[0])

    def test_si_persiste_solo_se_quita_la_frase_de_juicio(self):
        mala = (
            "Tu IRFI es 0.52, lo que significa un riesgo alto. "
            "De cada $100 que ganas, $58 van a deudas."
        )
        r, info = router.aplicar_guardrail(mala, self.CTX, lambda n: mala)
        self.assertNotIn("riesgo alto", r)
        self.assertIn("$58 van a deudas", r)
        self.assertTrue(info["frases_quitadas"])
        self.assertEqual(
            info["frases_final"], ["Tu IRFI es 0.52, lo que significa un riesgo alto."]
        )

    def test_si_todo_era_juicio_usa_el_mensaje_de_reformular(self):
        r, info = router.aplicar_guardrail(
            "Tu deuda es un problema, Ana.",
            self.CTX,
            lambda n: "Tu deuda es un problema, Ana.",
        )
        self.assertEqual(r, router.MENSAJE_REFORMULAR)

    def test_cifras_y_juicio_juntos_en_una_sola_correccion(self):
        notas = []
        r, info = router.aplicar_guardrail(
            "Te falta $4,054. Tu deuda es un problema.",
            self.CTX,
            lambda n: notas.append(n) or "Te faltan $6,044 para llegar.",
        )
        self.assertEqual(len(notas), 1)
        self.assertIn("$4,054", notas[0])
        self.assertIn("Habla sin juzgar", notas[0])
        self.assertEqual(r, "Te faltan $6,044 para llegar.")

    def test_respuesta_limpia_no_se_toca(self):
        llamadas = []
        r, info = router.aplicar_guardrail(
            "Te faltan $6,044. Lo manejable es hasta $40 de cada $100.",
            self.CTX,
            lambda n: llamadas.append(n) or "x",
        )
        self.assertEqual(llamadas, [])
        self.assertFalse(info["reintento"])

    def test_el_alias_antiguo_sigue_existiendo(self):
        self.assertIs(router.aplicar_guardrail_cifras, router.aplicar_guardrail)

    def test_el_bloque_de_retiro_pide_explicar_rendimiento(self):
        t = ctx.bloque_de_codigo(
            "PLAN",
            ana_madura(),
            "¿Cuánto tendría para el retiro si aporto $200 al mes?",
        )
        self.assertIn("Al decir 'rendimiento', explícalo en la misma frase", t)

    def test_el_bloque_de_datos_lleva_el_nombre_de_las_siglas(self):
        g = dict(TestArreglosSegundaCorridaReal.GRUPO)
        t = consulta_grupo.formatear(ana_primeriza(), g)
        self.assertIn("Índice de riesgo financiero, IRFI", t)
        self.assertIn("Índice de capacidad de ahorro, ICA", t)


class TestQuintaCorridaRouter(unittest.TestCase):
    SIM = (
        "Escenario: Independizarte / primera renta. Meta: $6,155. Horizonte: 12 meses. "
        "Ajuste de ahorro aplicado: 0%. Probabilidad de éxito: 67.3% (IC 95%: [66.4%, 68.2%]). "
        "Mediana del mes en que se alcanza la meta: mes 9."
    )
    # El contexto real incluye la pregunta de la persona ("10% más"): lo que ella
    # dijo no es una cifra inventada.
    CTX = SIM + " Te faltan $8,692. Pregunta: ¿Qué pasaría si ahorro 10% más?"

    # --- guardrail: snap, y porcentajes solo en SIMULACION --------------------
    def test_guardrail_corrige_la_resta_sin_regenerar(self):  # real: A1 madura
        llamadas = []
        r, info = router.aplicar_guardrail(
            "Te faltan $8,691 para llegar.",
            self.CTX,
            lambda n: llamadas.append(n) or "x",
        )
        self.assertEqual(r, "Te faltan $8,692 para llegar.")
        self.assertEqual(llamadas, [])
        self.assertFalse(info["reintento"])
        self.assertEqual(info["cifras_corregidas"], {"$8,691": "$8,692"})

    def test_probabilidad_inventada_se_reintenta_en_simulacion(
        self,
    ):  # real: C17 "74.2%"
        notas = []
        mala = "Con 10% más, la probabilidad de éxito fue de 74.2%."
        buena = "Para ver ese cambio, ajusta el control de ahorro en el Simulador."
        r, info = router.aplicar_guardrail(
            mala, self.CTX, lambda n: notas.append(n) or buena, incluir_porcentajes=True
        )
        self.assertEqual(r, buena)
        self.assertTrue(info["reintento"])
        self.assertEqual(info["cifras_primer_intento"], ["74.2%"])
        self.assertIn("74.2%", notas[0])

    def test_probabilidad_inventada_persistente_se_quita(self):
        mala = (
            "Con 10% más, la probabilidad de éxito fue de 74.2%. "
            "Prueba el Simulador para verlo con exactitud."
        )
        r, info = router.aplicar_guardrail(
            mala, self.CTX, lambda n: mala, incluir_porcentajes=True
        )
        self.assertNotIn("74.2%", r)
        self.assertIn("Simulador", r)

    def test_porcentajes_correctos_de_la_simulacion_pasan(self):
        llamadas = []
        r, info = router.aplicar_guardrail(
            "Tu probabilidad es de 67% (entre 66.4% y 68.2%).",
            self.CTX,
            lambda n: llamadas.append(n) or "x",
            incluir_porcentajes=True,
        )
        self.assertEqual(llamadas, [])  # 67% es redondeo de 67.3%

    def test_en_otras_categorias_un_porcentaje_derivado_no_dispara_nada(self):
        llamadas = []
        router.aplicar_guardrail(
            "Es el 58% de lo que ganas.", self.CTX, lambda n: llamadas.append(n) or "x"
        )
        self.assertEqual(llamadas, [])

    # --- qué pasaría si ----------------------------------------------------------
    def test_que_pasaria_si_se_detecta(self):
        for q in (
            "¿Qué pasaría si ahorro 10% más?",
            "¿Qué pasa si ahorro menos cada mes?",
            "¿Qué pasaría si gasto 5% menos?",
        ):
            self.assertTrue(router.es_pregunta_que_pasaria_si(q), q)
            self.assertEqual(router.clasificar_por_reglas(q), "SIMULACION", q)

    def test_que_pasaria_si_no_atrapa_otras_cosas(self):
        for q in (
            "¿Qué pasaría si aporto $200 al mes para el retiro?",  # eso lo proyecta plan_engine
            "¿Qué pasa si no pago mi tarjeta?",
            "¿Cuánto me queda cada mes?",
        ):
            self.assertFalse(router.es_pregunta_que_pasaria_si(q), q)

    def test_respuesta_que_pasaria_si_usa_solo_datos_reales(self):
        t = router.respuesta_que_pasaria_si(self.SIM, "Ana")
        self.assertTrue(t.startswith("Ana, no puedo recalcular"))
        self.assertIn("Simulador", t)
        self.assertIn("ajuste de ahorro de 0%", t)
        self.assertIn("67.3%", t)
        self.assertNotIn("74", t)

    def test_respuesta_que_pasaria_si_con_texto_raro_no_inventa_referencia(self):
        t = router.respuesta_que_pasaria_si("texto sin formato", None)
        self.assertTrue(t.startswith("No puedo recalcular"))
        self.assertNotIn("Como referencia", t)

    def test_roadmap_y_sin_simulacion_siguen_siendo_fijos(self):
        self.assertIn("Simulador", router.respuesta_sin_simulacion("Ana"))


class TestValidateSql(unittest.TestCase):
    RID = "PFT_0000636"

    def v(self, sql):
        return text_to_sql.validate_sql(sql, self.RID)

    def test_select_simple_sigue_valido(self):
        self.assertIsNone(
            self.v(
                "SELECT ingreso_mensual FROM gold.fact_comportamiento "
                "WHERE record_id = 'PFT_0000636'"
            )
        )
        self.assertIsNone(
            self.v(
                "SELECT income_type, AVG(ingreso_mensual) "
                "FROM gold.fact_comportamiento GROUP BY income_type"
            )
        )

    def test_detalle_con_filtro_del_perfil_activo_pasa(self):
        self.assertIsNone(
            self.v(
                "SELECT meta_ahorro_mensual FROM gold.fact_perfil_detalle "
                "WHERE record_id = 'PFT_0000636'"
            )
        )

    def test_detalle_sin_filtro_o_agregado_se_rechaza(self):
        self.assertIsNotNone(
            self.v("SELECT AVG(ahorro_del_mes) FROM gold.fact_perfil_detalle")
        )
        self.assertIsNotNone(self.v("SELECT * FROM gold.fact_perfil_detalle"))

    def test_detalle_de_la_otra_ana_se_rechaza(self):
        self.assertIsNotNone(
            self.v(
                "SELECT * FROM gold.fact_perfil_detalle "
                "WHERE record_id = 'PFT_0002539'"
            )
        )

    def test_detalle_con_or_o_union_se_rechaza(self):
        self.assertIsNotNone(
            self.v(
                "SELECT * FROM gold.fact_perfil_detalle "
                "WHERE record_id = 'PFT_0000636' OR 1=1"
            )
        )
        self.assertIsNotNone(
            self.v(
                "SELECT 1 FROM gold.fact_perfil_detalle "
                "WHERE record_id = 'PFT_0000636' UNION SELECT 2"
            )
        )

    def test_join_con_coma_a_detalle_tambien_exige_filtro(self):
        self.assertIsNotNone(
            self.v(
                "SELECT c.record_id FROM gold.fact_comportamiento c, "
                "gold.fact_perfil_detalle d"
            )
        )

    def test_otro_esquema_se_rechaza_aunque_no_este_en_from(self):
        self.assertIsNotNone(
            self.v(
                "SELECT 1 FROM gold.fact_comportamiento c, "
                "operational.quality_metrics q"
            )
        )

    def test_escritura_se_rechaza(self):
        self.assertIsNotNone(self.v("DELETE FROM gold.fact_comportamiento"))

    def test_detalle_en_allowed_tables_y_schema(self):
        self.assertIn("gold.fact_perfil_detalle", text_to_sql.ALLOWED_TABLES)
        self.assertIn("gold.fact_perfil_detalle", text_to_sql.SCHEMA_CONTEXT)
        self.assertNotIn("huella_", text_to_sql.SCHEMA_CONTEXT)


if __name__ == "__main__":
    unittest.main()
