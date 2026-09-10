# V0.6 - Confidence Engine + Market Refresh Pipeline

## Confidence score

`confidence_score` es un indice de calidad y coherencia de los datos observados.
No es una probabilidad de beneficio, venta o exito de una operacion.

El motor usa estos factores:

| Factor | Peso | Datos necesarios |
| --- | ---: | --- |
| `sales_sample` | 30% | `sales_6m` de una fuente de ventas |
| `price_dispersion` | 25% | p25, mediana y media ponderada de vendidos |
| `source_agreement` | 20% | p25 vendido BrickLink y p25/mediana asking eBay |
| `exact_identification` | 15% | coincidencia observable del `set_num` |
| `data_freshness` | 10% | `observed_at` de las fuentes disponibles |

Los factores ausentes permanecen como `None`. El motor suma solo los pesos de
los factores disponibles y divide la puntuacion ponderada por esa suma. No
convierte un dato ausente en cero.

Muestra de ventas:

- 0 ventas: `0.0`
- 1-4: `0.2`
- 5-11: `0.4`
- 12-29: `0.6`
- 30-59: `0.8`
- 60 o mas: `1.0`

Las etiquetas son `VERY_LOW`, `LOW`, `MEDIUM`, `HIGH` y `VERY_HIGH`.
Cuando no hay ningun factor calculable, score y etiqueta son `None`.

## Decision

Los umbrales economicos y de rotacion de V0.4 siguen vigentes. Con todos los
datos necesarios:

- Menos de `0.55`: `REJECT`.
- Entre `0.55` y `0.69`: `WATCH`, siempre que el resto de criterios sea razonable.
- Desde `0.70`: permite `PAPER_BUY` si tambien se cumplen margen y rotacion.
- Score ausente: `PENDING MARKET DATA`.

## Fuentes requeridas

BrickLink `guide_type=sold` aporta `sales_6m`, precios vendidos y dispersion.
eBay Browse aporta anuncios activos y su distribucion de precios asking. Los
precios asking no se tratan como ventas. Rebrickable aporta identidad y
catalogo.

## Refresh

`MarketRefreshPipeline` acepta un set o una lista. Por cada `set_num` consulta
los conectores configurados, agrega fuentes, calcula confianza y metricas, y
anade una observacion a `data/market_history.sqlite3`.

Estados:

- `PENDING`: ningun conector de mercado configurado.
- `PARTIAL`: solo una fuente disponible o una de las fuentes fallo.
- `OK`: BrickLink y eBay completaron el set.
- `ERROR`: ningun conector de mercado configurado pudo completar el set.

Cada set se confirma por separado. Los errores no detienen el lote. La pausa se
controla con `MARKET_REFRESH_PAUSE_SECONDS` y el checkpoint con
`MARKET_REFRESH_CHECKPOINT_EVERY`. Un `run_id` interrumpido puede continuar con
`resume=True`; los sets ya confirmados se omiten. El historico nunca se
sobrescribe.

Los logs incluyen conector, `set_num` y tipo de error. No incluyen mensajes de
excepcion, tokens ni secretos.

## Activacion

El boton del dashboard se habilita cuando BrickLink o eBay figure como `ACTIVE`.
No se ejecuta ningun refresh al arrancar Streamlit.

Para eBay:

```dotenv
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_ENVIRONMENT=sandbox
```

Para BrickLink:

```dotenv
BRICKLINK_CONSUMER_KEY=
BRICKLINK_CONSUMER_SECRET=
BRICKLINK_TOKEN=
BRICKLINK_TOKEN_SECRET=
```

Opciones de lote:

```dotenv
MARKET_REFRESH_PAUSE_SECONDS=0.5
MARKET_REFRESH_CHECKPOINT_EVERY=10
```

Verificacion:

```powershell
py -m pytest
py -m streamlit run dashboard/app.py
```
