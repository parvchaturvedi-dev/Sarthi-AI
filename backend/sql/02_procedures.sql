-- Nova auth PL/SQL procedures. Run after 01_schema.sql.

-- Register a local (email/password) user; returns the new id.
CREATE OR REPLACE PROCEDURE nova_register (
  p_email    IN  VARCHAR2,
  p_name     IN  VARCHAR2,
  p_hash     IN  VARCHAR2,
  p_provider IN  VARCHAR2,
  p_id       OUT NUMBER
) AS
BEGIN
  INSERT INTO nova_users (email, name, password_hash, provider)
  VALUES (LOWER(p_email), p_name, p_hash, p_provider)
  RETURNING id INTO p_id;
END;
/

-- Look up a user by email. p_id is NULL when not found.
CREATE OR REPLACE PROCEDURE nova_get_user (
  p_email    IN  VARCHAR2,
  p_id       OUT NUMBER,
  p_name     OUT VARCHAR2,
  p_hash     OUT VARCHAR2,
  p_provider OUT VARCHAR2
) AS
BEGIN
  SELECT id, name, password_hash, provider
    INTO p_id, p_name, p_hash, p_provider
    FROM nova_users
   WHERE email = LOWER(p_email);
EXCEPTION
  WHEN NO_DATA_FOUND THEN
    p_id := NULL;
END;
/

-- Find-or-create a Google user; returns the id.
CREATE OR REPLACE PROCEDURE nova_upsert_google (
  p_email IN  VARCHAR2,
  p_name  IN  VARCHAR2,
  p_id    OUT NUMBER
) AS
BEGIN
  SELECT id INTO p_id FROM nova_users WHERE email = LOWER(p_email);
EXCEPTION
  WHEN NO_DATA_FOUND THEN
    INSERT INTO nova_users (email, name, provider)
    VALUES (LOWER(p_email), p_name, 'google')
    RETURNING id INTO p_id;
END;
/
