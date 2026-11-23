-- Dedicated login for the scheduled outbox dispatcher.
-- Password is provisioned separately and never stored in Git.

CREATE ROLE image_to_lego_dispatcher_login
    LOGIN
    NOINHERIT
    CONNECTION LIMIT 3;
-- The dispatcher must explicitly assume its narrowly scoped
-- NOLOGIN role inside each database transaction.
GRANT image_to_lego_outbox_dispatcher
TO image_to_lego_dispatcher_login
WITH INHERIT FALSE, SET TRUE, ADMIN FALSE;
