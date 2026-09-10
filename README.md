# Arbitrage Engine V0 — LEGO / BrickLink

Objetivo: validar durante 14 días si podemos identificar oportunidades de compra de sets LEGO con margen neto esperado >=20% y beneficio >=50€, usando datos reales de ventas de BrickLink.

## Arquitectura V0

BrickLink Price Guide -> normalización -> valoración conservadora -> motor de oportunidad -> paper trading.

## 1. Credenciales BrickLink

BrickLink exige:
- Consumer Key
- Consumer Secret
- Access Token
- Token Secret
- IP estática registrada para el cliente que llama a la API

Registra el consumidor desde tu cuenta BrickLink y genera los tokens. Nunca subas las credenciales al repositorio.

Copia `.env.example` como `.env` y rellena las cuatro variables BrickLink.

## 2. Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

En Windows:
```bash
.venv\Scripts\activate
```

## 3. Primera prueba

Ejemplo:
```bash
python analyze_set.py 10295-1 90 --condition U
```

El programa:
1. valida el set en BrickLink;
2. obtiene Price Guide de ventas de los últimos 6 meses;
3. calcula un valor conservador;
4. estima comisiones, envío y otros costes;
5. devuelve `PAPER_BUY` o `REJECT`.

## Reglas iniciales

- Capital real: 1.000 €
- Primeros 14 días: solo paper trading
- Ticket máximo: 300 €
- Beneficio esperado mínimo: 50 €
- ROI esperado mínimo: 20%
- Mínimo de transacciones BrickLink en 6 meses: 5
- Confianza mínima: 70%

Estas reglas son V0 y se calibrarán con evidencia.

## Importante

BrickLink Price Guide no incluye IVA. El motor debe modelar por separado:
- comisiones reales del canal donde vendamos;
- transporte y embalaje;
- fiscalidad aplicable;
- estado/completitud del set;
- riesgo de piezas faltantes;
- diferencia entre precio de mercado y dinero neto recuperable.

La V0 NO compra automáticamente.


## Rebrickable — integración activa

Añade la clave en `.env`:

```env
REBRICKABLE_API_KEY=tu_clave_aqui
```

No compartas la clave en chats ni la subas a GitHub.

### Comprobar conexión

```bash
python test_rebrickable.py
```

Debe devolver los datos del set `10295-1`.

### Construir el universo V0

```bash
python build_lego_universe.py --min-year 2010 --max-year 2025 --min-parts 300
```

Genera `lego_universe_v0.csv`.

Para grandes extracciones del catálogo completo, Rebrickable recomienda usar sus archivos CSV de Downloads en lugar de hacer miles de llamadas a la API. Para V0 usamos la API únicamente para validar la integración y construir un universo filtrado.


## V0.6 — Confidence Engine + Market Refresh Pipeline

Confidence calculada solo con factores observables, refresh manual por set o
lotes e historico SQLite con checkpoint y reanudacion. Detalles: [V0.6](docs/V0_6_CONFIDENCE_AND_REFRESH.md).

## V0.5 — Market Connectors Ready

Adaptadores independientes para eBay Browse API y BrickLink Store API, modelo
normalizado y agregador con trazabilidad de fuentes. No se hacen llamadas de
mercado al arrancar. Configuracion: [V0.5](docs/V0_5_MARKET_CONNECTORS.md).

## V0.4 — dashboard de operaciones

Dashboard con siete pestañas, radar del catálogo local, analizador, lotes y
seguimiento de paper trades. Los datos de mercado ausentes permanecen pendientes.
La cartera real continúa vacía y no se ejecutan compras automáticas.

```powershell
py -m pytest
py -m streamlit run dashboard/app.py
```

Reglas y decisiones técnicas: [V0.4](docs/V0_4_CHANGES.md).

## V0.2 — modo offline / paper trading

La V0.2 ya funciona aunque BrickLink y eBay sigan pendientes.

### Analizar una oportunidad manual
```bash
python analyze_manual.py 90 150 --confidence 0.85 --sales-6m 12
```

### Analizar un lote
Edita `paper_trading/lot_template.csv` y ejecuta:
```bash
python analyze_lot.py 240 paper_trading/lot_template.csv
```

### Dashboard
```bash
streamlit run dashboard/app.py
```

### Tests
```bash
pytest
```

### Regla de diseño
Todas las fuentes externas son adaptadores. El motor central puede seguir funcionando con entrada manual, Rebrickable, BrickLink, eBay u otras fuentes futuras sin reescribir la lógica de negocio.


## V0.3 — solución al HTTP 429

Para catálogo masivo, usa el CSV oficial `sets.csv` de Rebrickable y filtra localmente:

```powershell
py build_lego_universe.py --csv sets.csv --min-year 2010 --max-year 2025 --min-parts 300
```

Si aún no tienes el CSV, el fallback por API es:

```powershell
py build_lego_universe.py --min-year 2010 --max-year 2025 --min-parts 300 --delay 2
```

Este modo ya incluye reintentos ante HTTP 429 y checkpoint.

La rotación pasa a ser criterio duro: menos de 2 ventas/mes o más de 45 días esperados de inmovilización => REJECT.
