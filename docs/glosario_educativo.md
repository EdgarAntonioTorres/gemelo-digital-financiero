# Glosario educativo — conceptos generales para Centavo

> A diferencia de `glosario_reglas_negocio.md` (que documenta CÓMO se construyó este proyecto) y `diccionario_features.md` (QUÉ significa cada columna de Gold), este documento explica conceptos de educación financiera básica que un adulto joven puede no conocer todavía. Es contenido general, no específico de este dataset — complementa a los otros 2 para que `t080` (RAG) tenga con qué responder la categoría B completa de `t076`.

---

## 1. Fondo de emergencia

Es dinero guardado aparte, que solo se toca para gastos imprevistos: perder el trabajo, una reparación urgente, un gasto médico. No es para vacaciones ni para un antojo — su único trabajo es estar ahí cuando algo sale mal.

La recomendación estándar de la industria financiera es tener entre 3 y 6 meses de tus gastos mensuales guardados. Si gastas $8,000 al mes, un fondo de emergencia completo estaría entre $24,000 y $48,000. Empezar con poco no es un fracaso — lo importante es que exista y vaya creciendo.

## 2. Ratio de endeudamiento

Compara cuánto de tu ingreso ya se va en pagar deudas (tarjetas, préstamos, crédito de auto) contra cuánto ganas en total. Se expresa como un porcentaje o una proporción: si ganas $10,000 y pagas $3,000 en deudas cada mes, tu ratio es 30%.

Entre más alto, menos margen tienes para imprevistos o para ahorrar — y los bancos lo usan para decidir si te prestan más. Un ratio por debajo de 35-40% suele considerarse manejable; arriba de eso empieza a ser una señal de alerta.

## 3. Score crediticio (buró de crédito)

Es un número que resume qué tan "confiable" has sido pagando deudas en el pasado: tarjetas, préstamos, servicios a crédito. Sube cuando pagas a tiempo y de forma constante; baja cuando te atrasas o dejas de pagar.

Los bancos lo revisan antes de darte una tarjeta, un préstamo o un crédito de auto — no es un juicio moral, es una foto de tu historial. Se construye con el tiempo: entre más historial de pagos puntuales tengas, mejor tiende a verse.

## 4. Tasa de interés

Es el costo de pedir dinero prestado, expresado como un porcentaje. Si pides $1,000 prestados a una tasa anual de 20%, en un año (sin abonar nada) deberías cerca de $1,200 — los $200 extra son el interés.

Importa en dos sentidos opuestos: cuando pides prestado, una tasa alta significa que pagas mucho más de lo que pediste. Cuando ahorras o inviertes, una tasa alta a tu favor significa que tu dinero crece más rápido. Vale la pena siempre preguntar la tasa antes de aceptar cualquier crédito.

## 5. Rentar vs. comprar (una vivienda)

Rentar significa pagar cada mes por usar un lugar que es de alguien más — sin compromiso a largo plazo, pero sin construir nada tuyo con ese dinero. Comprar significa que, poco a poco, el lugar se vuelve tuyo — pero requiere un enganche grande al inicio, un compromiso de años, y gastos que rentar no tiene (mantenimiento, impuestos).

No hay una respuesta universal: depende de cuánto tiempo planeas quedarte en un lugar, cuánto ahorro tienes disponible ahora, y qué tan estable es tu ingreso. Para alguien empezando su vida laboral, rentar suele ser el paso natural mientras se junta el ahorro y la estabilidad para comprar.

## 6. Tarjeta de crédito: fecha de corte y pago mínimo

La **fecha de corte** es el día del mes en que la tarjeta "cierra" tus compras del periodo y arma tu estado de cuenta. Todo lo que compraste antes de esa fecha aparece en ese corte; lo que compres después, aparece hasta el siguiente.

El **pago mínimo** es la cantidad más chica que puedes pagar para no caer en mora — pero pagar solo el mínimo significa que el resto de la deuda sigue generando intereses, a veces altos. Pagar el total cada mes (o lo más cerca posible) es la única forma de usar una tarjeta sin que el interés se coma tu dinero.

## 7. Ahorro automático ("pagarte primero")

Es la idea de que, en cuanto te llega tu ingreso, una parte se aparta para ahorro ANTES de gastar en cualquier otra cosa — en vez de esperar a ver "qué sobra" al final del mes (que casi nunca es lo que uno planeaba).

Se le llama "pagarte primero" porque trata tu ahorro como si fuera una deuda contigo mismo, con la misma prioridad que pagar la renta o el celular. Automatizarlo (una transferencia programada el día que cobras) quita la necesidad de fuerza de voluntad — el dinero ya está apartado antes de que puedas gastarlo.

## 8. Cómo se calculan las metas del Simulador

Cada uno de los 3 escenarios del Simulador (`t068`-`t070`) usa una fórmula distinta para calcular cuánto dinero necesitas juntar. Ninguna es un número inventado al azar — cada una sigue una convención estándar de asesoría financiera básica:

- **Independizarte / primera renta:** tu meta es **2 veces tu gasto mensual**. Esto cubre el depósito en garantía más el primer mes de renta adelantado — la convención más común al rentar un lugar.
- **Primer vehículo:** tu meta es **3 veces tu ingreso mensual**. Es el enganche típico recomendado para un primer auto (3 meses de ingreso como enganche).
- **Cambio de empleo / colchón de emergencia:** tu meta es la **brecha que te falta para cubrir 3 meses de gasto con tu fondo de emergencia** (el extremo bajo del benchmark de industria de 3 a 6 meses). Si ya cubres esos 3 meses, tu meta es $0 — no se te pide ahorrar de más solo porque sí.

Estas 3 fórmulas están pendientes de aprobación formal del mentor del proyecto — son una propuesta razonada, no una regla ya cerrada de forma definitiva.