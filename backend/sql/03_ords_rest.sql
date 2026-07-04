-- Exposes the auth as REST endpoints (apex.oracle.com has no external DB access,
-- so the backend calls these over HTTPS instead of connecting directly).
-- Run in your APEX Workspace: SQL Workshop -> SQL Commands. Run 01_schema.sql first.
--
-- After running, your base URL will be:
--   https://oracleapex.com/ords/novadb/nova/auth
-- Put that in backend/.env as ORDS_BASE_URL.

BEGIN
  -- give this schema a predictable REST prefix: /ords/novadb/
  ORDS.ENABLE_SCHEMA(
    p_enabled             => TRUE,
    p_url_mapping_type    => 'BASE_PATH',
    p_url_mapping_pattern => 'novadb',
    p_auto_rest_auth      => FALSE);

  ORDS.DEFINE_MODULE(
    p_module_name => 'nova.auth',
    p_base_path   => '/nova/auth/');

  -- POST /register  {email,name,hash,provider} -> {"id": <n> | -1 if duplicate}
  ORDS.DEFINE_TEMPLATE(p_module_name => 'nova.auth', p_pattern => 'register');
  ORDS.DEFINE_HANDLER(
    p_module_name => 'nova.auth', p_pattern => 'register', p_method => 'POST',
    p_source_type => ORDS.source_type_plsql,
    p_source => q'~
BEGIN
  INSERT INTO nova_users (email, name, password_hash, provider)
  VALUES (LOWER(:email), :name, :hash, :provider)
  RETURNING id INTO :id;
EXCEPTION WHEN DUP_VAL_ON_INDEX THEN
  :id := -1;
END;
~');

  -- GET /user?email=...  -> {id,name,password_hash,provider}  (404 if none)
  ORDS.DEFINE_TEMPLATE(p_module_name => 'nova.auth', p_pattern => 'user');
  ORDS.DEFINE_HANDLER(
    p_module_name => 'nova.auth', p_pattern => 'user', p_method => 'GET',
    p_source_type => ORDS.source_type_query_one_row,
    p_source => 'SELECT id, name, password_hash, provider FROM nova_users WHERE email = LOWER(:email)');

  -- POST /google  {email,name} -> {"id": <n>}  (find or create)
  ORDS.DEFINE_TEMPLATE(p_module_name => 'nova.auth', p_pattern => 'google');
  ORDS.DEFINE_HANDLER(
    p_module_name => 'nova.auth', p_pattern => 'google', p_method => 'POST',
    p_source_type => ORDS.source_type_plsql,
    p_source => q'~
BEGIN
  SELECT id INTO :id FROM nova_users WHERE email = LOWER(:email);
EXCEPTION WHEN NO_DATA_FOUND THEN
  INSERT INTO nova_users (email, name, provider)
  VALUES (LOWER(:email), :name, 'google') RETURNING id INTO :id;
END;
~');

  COMMIT;
END;
/
