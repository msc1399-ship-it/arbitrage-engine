# V0.5 - Market Connectors Ready

V0.5 separa identidad, oferta activa e historico vendido. El dashboard no llama
a ninguna API al arrancar y el boton de actualizacion de mercado permanece
deshabilitado.

## Fuentes

- Rebrickable aporta identidad y catalogo.
- BrickLink Price Guide con `guide_type=sold` aporta historico de seis meses.
- eBay Browse API aporta exclusivamente anuncios activos.
- Cada metrica agregada conserva su fuente en `derived_metrics.sources`.
- Una ausencia permanece como `None`; no se convierte en cero.

La confianza queda en `None` en ambos adaptadores porque las respuestas no
incluyen una medida equivalente. Sin una confianza procedente de una fuente
valida, la decision agregada es `PENDING MARKET DATA`.

## Activar eBay

Crear un keyset en eBay Developers para el entorno elegido y completar:

```dotenv
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_ENVIRONMENT=sandbox
```

`EBAY_ENVIRONMENT` admite `sandbox` o `production`. El cliente obtiene un token
OAuth de aplicacion mediante client credentials y consulta Browse API con el
marketplace `EBAY_ES`. Browse no ofrece aqui historico vendido: `sales_6m` y los
precios vendidos permanecen en `None`.

## Activar BrickLink

Crear credenciales OAuth 1.0 de Store API y completar:

```dotenv
BRICKLINK_CONSUMER_KEY=
BRICKLINK_CONSUMER_SECRET=
BRICKLINK_TOKEN=
BRICKLINK_TOKEN_SECRET=
```

El adaptador admite `get_item()` y `get_price_guide()` para condiciones `N` o
`U`, moneda `EUR` y guias `sold` o `stock`. El agregador prioriza la guia
`sold` de BrickLink para ventas y eBay para anuncios activos.

## Verificacion

```powershell
py -m pytest
py -m streamlit run dashboard/app.py
```
