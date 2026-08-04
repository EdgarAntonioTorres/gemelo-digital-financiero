# /src/ml

Código de modelado predictivo y simulación (Fase 5):

- Entrenamiento y evaluación del modelo de riesgo (Logistic Regression baseline
  → XGBoost/LightGBM), segmentado <30 años (t061-t066).
- Motor del simulador Monte Carlo (numpy/scipy) para los 3 escenarios:
  renta, auto, tarjeta/empleo (t067-t073).
- Modelos serializados (`.pkl` / `.onnx`) se guardan aquí bajo `/models`
  (no versionar los binarios pesados; usar Git LFS o excluir vía `.gitignore`).
