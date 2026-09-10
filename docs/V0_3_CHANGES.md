# V0.3

- Bulk catalog via Rebrickable CSV is now the preferred path.
- API fallback has exponential backoff for HTTP 429, delay between pages and checkpointing.
- Rotation is a hard gate: minimum 2 sales/month and expected sell-through <=45 days.
- Opportunity score gives 25% weight to liquidity plus 10% to capital efficiency.
- High-margin but slow-moving items are rejected.
