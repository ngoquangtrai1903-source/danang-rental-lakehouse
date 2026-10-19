ALTER TABLE gold.rental_room
    ALTER COLUMN has_balcony TYPE SMALLINT
        USING has_balcony::INTEGER,
    ALTER COLUMN free_hours TYPE SMALLINT
        USING free_hours::INTEGER,
    ALTER COLUMN has_camera_security TYPE SMALLINT
        USING has_camera_security::INTEGER,
    ALTER COLUMN has_elevator TYPE SMALLINT
        USING has_elevator::INTEGER,
    ALTER COLUMN has_mezzanine TYPE SMALLINT
        USING has_mezzanine::INTEGER,
    ALTER COLUMN private_bathroom TYPE SMALLINT
        USING private_bathroom::INTEGER,
    ALTER COLUMN wifi TYPE SMALLINT
        USING wifi::INTEGER,
    ALTER COLUMN has_parking TYPE SMALLINT
        USING has_parking::INTEGER,
    ALTER COLUMN has_window TYPE SMALLINT
        USING has_window::INTEGER;

ALTER TABLE gold.rental_room
    ADD CONSTRAINT ck_gold_rental_room_feature_flags CHECK (
        (has_balcony IS NULL OR has_balcony IN (0, 1))
        AND (free_hours IS NULL OR free_hours IN (0, 1))
        AND (has_camera_security IS NULL OR has_camera_security IN (0, 1))
        AND (has_elevator IS NULL OR has_elevator IN (0, 1))
        AND (has_mezzanine IS NULL OR has_mezzanine IN (0, 1))
        AND (private_bathroom IS NULL OR private_bathroom IN (0, 1))
        AND (wifi IS NULL OR wifi IN (0, 1))
        AND (has_parking IS NULL OR has_parking IN (0, 1))
        AND (has_window IS NULL OR has_window IN (0, 1))
    );
