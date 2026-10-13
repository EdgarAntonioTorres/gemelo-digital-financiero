"""
Pruebas de `assistant/verificaciones_respuesta.py`. Los casos "reales" son
frases textuales que produjo el modelo en las corridas de la Sesión 36.
Sin Ollama ni BD: solo `unittest`.
"""

from __future__ import annotations

import unittest

from assistant import verificaciones_respuesta as vr

CONTEXTO = (
    "Fondo de emergencia: $541. Colchón de 3 meses: objetivo $9,232, te faltan "
    "$8,692. Ahorro del mes: $627 (17% del ingreso). Lo manejable es hasta $40 "
    "de cada $100. Rendimiento 6.0% anual real. Meta $2,347. Aporte $200."
)


class TestCifras(unittest.TestCase):
    def test_resta_del_modelo_se_detecta(self):  # real: "Te faltan $8,691"
        self.assertEqual(
            vr.cifras_sin_respaldo("Te faltan $8,691.", CONTEXTO), ["$8,691"]
        )

    def test_cifras_correctas_pasan(self):
        r = "Tienes $541, necesitas $9,232 y te faltan $8,692. Ahorras $627 (17%)."
        self.assertEqual(vr.cifras_sin_respaldo(r, CONTEXTO), [])

    def test_probabilidad_inventada(self):  # real: "La probabilidad ... $71.16%"
        self.assertIn(
            "71.16%", vr.cifras_sin_respaldo("La probabilidad es de 71.16%", CONTEXTO)
        )

    def test_formatos_equivalentes(self):
        self.assertEqual(vr.cifras_sin_respaldo("Son $8692 y $541.00", CONTEXTO), [])
        self.assertEqual(vr.cifras_sin_respaldo("rinde 6% al año", CONTEXTO), [])

    def test_coma_final_no_rompe(self):
        self.assertEqual(vr.cifras_sin_respaldo("Tienes $541, así que", CONTEXTO), [])

    def test_fuga_de_cifra_de_ejemplo(self):  # real: "tu ingreso de $2,952"
        self.assertEqual(
            vr.cifras_sin_respaldo("cerca de tu ingreso de $2,952", CONTEXTO),
            ["$2,952"],
        )


class TestTextoPegado(unittest.TestCase):
    def test_casos_reales(self):
        self.assertTrue(vr.texto_pegado("Te faltan$6,043."))  # $ pegado a palabra
        self.assertEqual(vr.texto_pegado("tu gasto ($2,443)es por debajo"), [")e"])
        self.assertEqual(
            vr.texto_pegado("Si continuas ahorrando $627 almes, llegarías"), ["almes"]
        )

    def test_digito_pegado_a_palabra(self):
        self.assertTrue(vr.texto_pegado("$72,000serían tus aportaciones"))

    def test_texto_normal_no_marca(self):
        self.assertEqual(
            vr.texto_pegado("Ahorras $627 al mes (el 17%) y te faltan $8,692."), []
        )


class TestForma(unittest.TestCase):
    def test_palabras_por_frase(self):
        self.assertEqual(
            vr.palabras_por_frase("Hola Ana. Tienes cuatro palabras aquí."), 3.0
        )

    def test_no_parte_dentro_de_una_cifra(self):
        self.assertEqual(vr.palabras_por_frase("Ganas $3,704.29 al mes."), 4.0)

    def test_vacio(self):
        self.assertEqual(vr.palabras_por_frase("   "), 0.0)


class TestJergaYSiglas(unittest.TestCase):
    def test_termino_sin_explicar(self):
        self.assertIn(
            "rendimiento", vr.terminos_sin_explicar("Tu rendimiento será alto.")
        )

    def test_termino_explicado_no_marca(self):
        t = "El interés compuesto significa que tu dinero genera más dinero cada año."
        self.assertNotIn("interés compuesto", vr.terminos_sin_explicar(t))

    def test_sigla_sola(self):
        self.assertEqual(vr.siglas_solas("Tu IRFI es 0.52."), ["IRFI"])
        self.assertEqual(
            vr.siglas_solas("Tu índice de riesgo financiero, el IRFI, es 0.52."), []
        )


class TestBarreras(unittest.TestCase):
    def test_frases_prohibidas(self):
        self.assertTrue(vr.frases_prohibidas("Lo siento, no calificas para eso."))
        self.assertFalse(vr.frases_prohibidas("No puedo darte esa recomendación."))

    def test_bancos(self):
        self.assertEqual(
            vr.bancos_o_marcas("Te conviene BBVA o Santander"), ["BBVA", "Santander"]
        )
        self.assertFalse(vr.bancos_o_marcas("Una cuenta de ahorro sirve."))

    def test_bajo_riesgo_con_6(self):
        self.assertTrue(
            vr.bajo_riesgo_con_rendimiento("Una inversión de bajo riesgo rinde 6.0%.")
        )
        self.assertFalse(
            vr.bajo_riesgo_con_rendimiento(
                "Es de bajo riesgo. El supuesto es 6.0% anual."
            )
        )

    def test_dolares(self):
        self.assertTrue(vr.sin_aclarar_dolares("Tienes $541."))
        self.assertFalse(
            vr.sin_aclarar_dolares("Tienes $541 (en dólares, así vienen tus datos).")
        )
        self.assertFalse(vr.sin_aclarar_dolares("Hola Ana."))

    def test_nivel1_recomienda_inversion(self):
        self.assertTrue(
            vr.nivel1_recomienda_inversion("Te conviene invertir ya.", "PRODUCTO", 1)
        )
        self.assertFalse(
            vr.nivel1_recomienda_inversion("Te conviene invertir ya.", "PRODUCTO", 2)
        )
        self.assertFalse(
            vr.nivel1_recomienda_inversion("Te conviene invertir ya.", "PLAN", 1)
        )


class TestTercerCorridaReal(unittest.TestCase):
    """Casos textuales del informe t082 (62 respuestas, Sesión 36)."""

    def test_porcentaje_con_coma_decimal_no_es_falso_positivo(self):
        # real: "67,3%" se leía como "3%" y se marcaba como cifra sin respaldo
        self.assertEqual(
            vr.cifras_sin_respaldo(
                "la probabilidad es de 67,3%", "Probabilidad de éxito: 67.3%"
            ),
            [],
        )
        self.assertEqual(
            vr.cifras_sin_respaldo(
                "entre el 66,4% y el 68,2%", "IC 95%: [66.4%, 68.2%]"
            ),
            [],
        )

    def test_porcentaje_con_coma_inventado_si_se_detecta(self):
        self.assertEqual(
            vr.cifras_sin_respaldo("es de 71,16%", "Probabilidad 67.3%"), ["71,16%"]
        )

    def test_solo_dolares_ignora_porcentajes(self):
        ctx = "Meta $2,194."
        self.assertEqual(
            vr.cifras_sin_respaldo("Es el 59% y son $2,194.", ctx, solo_dolares=True),
            [],
        )
        self.assertEqual(
            vr.cifras_sin_respaldo("Son $4,054 y el 59%.", ctx, solo_dolares=True),
            ["$4,054"],
        )

    def test_tono_juicio_casos_reales(self):
        self.assertTrue(vr.tono_juicio("Eso no es muy saludable."))  # E27 primeriza
        self.assertTrue(
            vr.tono_juicio("debes ser cuidadoso con tus decisiones")
        )  # E30 primeriza
        self.assertTrue(
            vr.tono_juicio("parece que estás un poco endeudada")
        )  # E27 primeriza
        self.assertTrue(
            vr.tono_juicio("Tu IRFI (0.52) es un poco más alto que lo ideal")
        )  # E30 primeriza
        self.assertEqual(
            vr.tono_juicio("Tu deuda es de $58 de cada $100 que ganas."), []
        )

    def test_umbral_inventado_casos_reales(self):
        self.assertTrue(
            vr.umbral_inventado("Tu ICA es 0,48: tienes una alta capacidad de ahorro.")
        )  # A4 madura
        self.assertTrue(
            vr.umbral_inventado("Tu IRFI (0.52) es moderado, pero no extremo.")
        )  # A4 primeriza
        self.assertEqual(
            vr.umbral_inventado("Un valor más alto indica que tienes más riesgo."), []
        )
        self.assertEqual(
            vr.umbral_inventado("El IRFI es 0.52. Más alto significa más riesgo."), []
        )


class TestCuartaCorridaReal(unittest.TestCase):
    """Casos textuales del informe t082 de 186 respuestas (3 corridas)."""

    # --- falsos positivos que se corrigieron --------------------------------
    def test_redondeo_de_porcentajes_no_es_inventado(self):
        self.assertEqual(
            vr.cifras_sin_respaldo("hay 67% de probabilidad", "Probabilidad 67.3%"), []
        )
        self.assertEqual(
            vr.cifras_sin_respaldo("casi el 80%", "Proporción de gasto esencial: 79%"),
            [],
        )

    def test_porcentaje_realmente_inventado_se_detecta(
        self,
    ):  # real: C17 "27% del ingreso"
        ctx = "Ahorro 17% del ingreso. Probabilidad 67.3%. Meta 29%."
        self.assertEqual(
            vr.cifras_sin_respaldo("es decir, a 27% del ingreso", ctx), ["27%"]
        )

    def test_siglas_definidas_una_vez_no_marcan(self):  # real: A4
        t = "Tu ICA (Índice de Capacidad de Ahorro) es 0.28. El ICA es una medida del ahorro."
        self.assertEqual(vr.siglas_solas(t), [])

    def test_siglas_nunca_definidas_si_marcan(self):  # real: A5 "tu IRFI ..."
        self.assertEqual(
            vr.siglas_solas("Tu IRFI está por encima del promedio."), ["IRFI"]
        )

    def test_no_puedes_evitar_no_es_un_dictamen(
        self,
    ):  # real: B14 "gastos que no puedes evitar"
        self.assertEqual(
            vr.frases_prohibidas("solo para gastos urgentes que no puedes evitar"), []
        )
        self.assertTrue(vr.frases_prohibidas("no puedes alcanzar esa meta"))

    def test_lo_ideal_sobre_el_fondo_no_marca(self):
        self.assertEqual(
            vr.tono_juicio("Lo ideal es tener entre 3 y 6 meses de gasto guardados."),
            [],
        )

    def test_nivel1_antes_de_invertir_es_lo_correcto(self):  # real: E29 c3
        self.assertFalse(
            vr.nivel1_recomienda_inversion(
                "Ana, antes de empezar a invertir, es importante que ordenes la base.",
                "PRODUCTO",
                1,
            )
        )
        self.assertTrue(
            vr.nivel1_recomienda_inversion(
                "Te recomiendo empezar a invertir un poco cada mes.", "PRODUCTO", 1
            )
        )

    # --- lo que se había escapado ---------------------------------------------
    def test_es_un_problema_es_juicio(self):  # real: E24 primeriza c2
        self.assertTrue(vr.tono_juicio("Tu deuda es un problema, Ana."))

    def test_riesgo_alto_con_irfi_es_umbral_inventado(self):  # real: E24 primeriza c2
        self.assertTrue(
            vr.umbral_inventado(
                "Tu IRFI es 0.52, lo que significa que estás tomando un riesgo alto."
            )
        )
        self.assertTrue(
            vr.umbral_inventado(
                "Tienes un IRFI de 0.42, un rango moderado de riesgo financiero."
            )
        )  # A4 c3

    def test_lo_ideal_invertido_sobre_la_deuda(self):  # real: A3 madura c1
        self.assertTrue(vr.tono_juicio("Lo ideal sería llegar a $40 de cada $100."))

    def test_frases_de_juicio_devuelve_frases_completas(self):
        t = (
            "Tu deuda es un problema, Ana. "
            "Lo manejable es hasta $40 de cada $100. "
            "Tu IRFI es moderado."
        )
        self.assertEqual(
            vr.frases_de_juicio(t),
            ["Tu deuda es un problema, Ana.", "Tu IRFI es moderado."],
        )
        self.assertEqual(vr.frases_de_juicio("Hola Ana. Tienes $541."), [])


class TestQuintaCorridaReal(unittest.TestCase):
    """Casos textuales del segundo informe de 186 respuestas."""

    CTX = (
        "Ahorro del mes: $1,411. Te faltan $8,692. Te faltan $6,044. "
        "Lo manejable es hasta $40 de cada $100."
    )

    def test_resta_de_redondeo_se_corrige(self):  # real: A1 madura "$1,412"
        texto, cambios = vr.reparar_montos_cercanos(
            "Te quedan $1,412 cada mes.", self.CTX
        )
        self.assertEqual(texto, "Te quedan $1,411 cada mes.")
        self.assertEqual(cambios, {"$1,412": "$1,411"})

    def test_otras_restas_reales(self):
        for mal, bien in (("$8,691", "$8,692"), ("$6,043", "$6,044")):
            texto, _ = vr.reparar_montos_cercanos(f"Te faltan {mal}.", self.CTX)
            self.assertEqual(texto, f"Te faltan {bien}.")

    def test_monto_lejano_no_se_toca(self):  # real: E25 "$4,054" (eran $6,044)
        texto, cambios = vr.reparar_montos_cercanos("Te faltan $4,054.", self.CTX)
        self.assertEqual(texto, "Te faltan $4,054.")
        self.assertEqual(cambios, {})

    def test_montos_chicos_no_se_corrigen(self):
        # $41 vs $40: con cantidades chicas $1 sí cambia el sentido
        texto, cambios = vr.reparar_montos_cercanos(
            "Lo manejable es hasta $41.", self.CTX
        )
        self.assertEqual(cambios, {})

    def test_monto_correcto_no_cambia(self):
        texto, cambios = vr.reparar_montos_cercanos("Te faltan $8,692.", self.CTX)
        self.assertEqual((texto, cambios), ("Te faltan $8,692.", {}))

    def test_no_reemplaza_a_medias_un_numero_mas_largo(self):
        texto, _ = vr.reparar_montos_cercanos(
            "Son $1,412 y también $1,412,000.", self.CTX
        )
        self.assertIn("$1,412,000", texto)
        self.assertTrue(texto.startswith("Son $1,411 y"))

    def test_buena_capacidad_de_ahorro_es_umbral_inventado(self):  # real: A4 madura c3
        self.assertTrue(
            vr.umbral_inventado("En tu caso, tienes una buena capacidad de ahorro.")
        )
        self.assertTrue(vr.umbral_inventado("Tienes un riesgo financiero moderado."))
        self.assertTrue(
            vr.frases_de_juicio(
                "Hola Ana. En tu caso, tienes una buena capacidad de ahorro."
            )
        )

    def test_explicacion_neutral_no_marca(self):
        self.assertEqual(
            vr.umbral_inventado(
                "El ICA mide cuánta capacidad tienes para ahorrar, y más alto es mejor."
            ),
            [],
        )


class TestVerificar(unittest.TestCase):
    def test_agrega_todas_las_banderas(self):
        v = vr.verificar("Tu IRFI es alto y te faltan $8,691.", CONTEXTO, "PERFIL", 1)
        self.assertEqual(v["cifras_sin_respaldo"], ["$8,691"])
        self.assertEqual(v["siglas_solas"], ["IRFI"])
        self.assertTrue(v["sin_aclarar_dolares"])
        self.assertEqual(
            set(v),
            {
                "palabras_por_frase",
                "cifras_sin_respaldo",
                "texto_pegado",
                "terminos_sin_explicar",
                "siglas_solas",
                "frases_prohibidas",
                "tono_juicio",
                "umbral_inventado",
                "bancos_o_marcas",
                "bajo_riesgo_con_6pct",
                "sin_aclarar_dolares",
                "nivel1_recomienda_inversion",
            },
        )


if __name__ == "__main__":
    unittest.main()
