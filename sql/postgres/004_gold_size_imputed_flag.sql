ALTER TABLE gold.rental_room
    ADD COLUMN IF NOT EXISTS size_imputed_flag SMALLINT NOT NULL DEFAULT 0
        CHECK (size_imputed_flag IN (0, 1));
