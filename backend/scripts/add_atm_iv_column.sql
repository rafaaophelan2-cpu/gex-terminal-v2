-- Agrega la columna necesaria para el percentil REAL de IV (ver
-- app/domain/iv_percentile.py). Nullable, sin default destructivo: no
-- rompe ninguna fila existente ni ningún insert que todavía no la use.
-- Correr una sola vez en el SQL Editor de Supabase.

ALTER TABLE gex_intraday
  ADD COLUMN IF NOT EXISTS atm_iv double precision;
