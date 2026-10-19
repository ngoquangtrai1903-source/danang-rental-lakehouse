ALTER TABLE gold.rental_room
    ALTER COLUMN has_balcony TYPE SMALLINT USING has_balcony::INTEGER,
    ALTER COLUMN free_hours TYPE SMALLINT USING free_hours::INTEGER,
    ALTER COLUMN has_camera_security TYPE SMALLINT USING has_camera_security::INTEGER,
    ALTER COLUMN has_elevator TYPE SMALLINT USING has_elevator::INTEGER,
    ALTER COLUMN has_mezzanine TYPE SMALLINT USING has_mezzanine::INTEGER,
    ALTER COLUMN private_bathroom TYPE SMALLINT USING private_bathroom::INTEGER,
    ALTER COLUMN wifi TYPE SMALLINT USING wifi::INTEGER,
    ALTER COLUMN has_parking TYPE SMALLINT USING has_parking::INTEGER,
    ALTER COLUMN has_window TYPE SMALLINT USING has_window::INTEGER;
