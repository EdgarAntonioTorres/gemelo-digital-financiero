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

Estas 3 fórmulas fueron revisadas y aprobadas por el mentor del proyecto (Sesión 36).

## 9. Cuenta de ahorro

Es una cuenta pensada para guardar dinero, separada de la que usas para tus gastos del día a día. Tenerla aparte ayuda a no gastar sin querer lo que juntaste, sobre todo el fondo de emergencia.

Su ventaja principal es la disponibilidad: puedes sacar tu dinero cuando lo necesites. Antes de abrir una, conviene preguntar si cobra comisiones y cuánto paga de interés, porque eso cambia de una institución a otra.

## 10. Ahorro programado

Es una instrucción que das una sola vez: "cada que me llegue mi ingreso, aparta esta cantidad hacia mi ahorro". A partir de ahí el dinero se mueve solo, el mismo día que cobras, sin depender de tu fuerza de voluntad.

Es la forma práctica de "pagarte primero" (ver el concepto 7). Puedes empezar con una cantidad pequeña y subirla poco a poco; lo importante es la constancia, no el monto inicial.

## 11. Inversión de bajo riesgo

Invertir es poner tu dinero en algo que puede crecer con el tiempo, a cambio de aceptar que el valor puede subir o bajar. "Bajo riesgo" quiere decir que se espera que el valor se mueva poco, no que sea imposible perder: ninguna inversión es completamente segura ni garantiza una ganancia.

Una regla básica es invertir solo lo que no vas a necesitar pronto, y después de tener un fondo de emergencia en marcha, para no verte obligado a vender en un mal momento. Empezar con un monto pequeño sirve para aprender y crear el hábito.

## 12. Ahorro para el retiro

Es dinero que apartas hoy para vivir tranquilo cuando ya no trabajes. Aunque parezca lejano, empezar temprano marca una gran diferencia por el interés compuesto: tu dinero genera rendimiento, y ese rendimiento también genera más rendimiento, año tras año.

Por eso, entre más temprano empiezas, más tiempo trabaja tu dinero a tu favor: aportar poco durante muchos años puede pesar más que aportar mucho durante pocos. En Moneta, las proyecciones de retiro son ilustrativas: usan por defecto un rendimiento supuesto de 6.0% anual real (descuenta la inflación, así que el resultado está en dólares de hoy), con un plazo de 30 años que se puede cambiar entre 10 y 40. Es un supuesto del escenario, no una promesa ni el rendimiento de un producto en particular.

## 13. Madurez financiera: cómo se calcula tu nivel

Moneta te asigna un nivel de madurez financiera a partir de tus hábitos, no de lo que sabes. Se calcula con dos datos: qué parte de tu ingreso se va en pagar deudas y cuántos meses de gasto cubre tu fondo de emergencia.

- **Nivel 1, Primeros pasos:** de cada $100 que ganas, más de $40 se van en pagar deudas. Lo primero es ordenar la base.
- **Nivel 2, Construyendo base:** tus deudas están en un nivel manejable (hasta $40 de cada $100 que ganas), pero tu fondo de emergencia aún no cubre 3 meses de gasto.
- **Nivel 3, Creciendo:** deudas manejables y un fondo que cubre 3 meses de gasto o más.

El nivel sirve para darte recomendaciones a tu medida: cambia qué te sugiere Centavo, no cómo te lo explica.