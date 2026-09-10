# V0.4

- Dashboard con RADAR, OPORTUNIDADES, ANALIZADOR, LOTES, PAPER TRADES, CARTERA y SISTEMA.
- Catalogo local automatico; campos de mercado ausentes permanecen pendientes.
- Rechazo obligatorio por menos de 2 ventas/mes o mas de 45 dias estimados.
- WATCH requiere al menos el 90% de ambos umbrales economicos y todos los criterios de riesgo.
- MAX BUY PRICE redondeado hacia abajo al centimo para respetar ambos umbrales y ticket de 300 EUR.
- profit_per_30_days es un indicador comparativo, no una rentabilidad garantizada.
- Costes del analizador: configuracion existente; costes de lotes: valores existentes del motor.
- Registro local de paper trades desde el analizador y seguimiento sin borrar filas historicas.
- Capital real intacto; no hay compras automaticas.
- Rebrickable ACTIVE indica clave configurada, no una comprobacion remota de validez.
- BrickLink depende de sus cuatro credenciales. eBay sigue PENDING: no existe colector implementado.

## Ejecucion

```powershell
py -m pytest
py -m streamlit run dashboard/app.py
```

El radar se recalcula al cargar la app o interactuar con ella. Las columnas de entrada son
market_value, conservative_value, current_listing_price, sales_6m, active_listings y confidence.
Los campos derivados se recalculan; nunca se reutilizan decisiones de una fila sin datos suficientes.
La confianza debe proceder de una fuente o evaluacion manual, no del catalogo Rebrickable.
