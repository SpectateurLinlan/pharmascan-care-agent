-- OWNER APPROVAL REQUIRED: creates one INACTIVE job, not a schema migration.
-- Prerequisites: reviewed one-shot/device result, pg_net, extensions.hmac,
-- and exactly one Vault secret named medithread_push_dispatch_hmac.
-- No real secret belongs in this file or cron.job.command.
BEGIN;
DO $prepare$
DECLARE
  job_id bigint;
BEGIN
  IF EXISTS(SELECT 1 FROM cron.job WHERE jobname='medithread-push-minute') THEN
    RAISE EXCEPTION 'Named dispatcher job already exists; inspect before changing';
  END IF;
  IF (SELECT count(*) FROM vault.secrets
      WHERE name='medithread_push_dispatch_hmac') <> 1 THEN
    RAISE EXCEPTION 'Exactly one dispatcher Vault secret is required';
  END IF;
  IF to_regprocedure('extensions.hmac(bytea,bytea,text)') IS NULL
     OR to_regclass('net.http_request_queue') IS NULL THEN
    RAISE EXCEPTION 'Required HMAC/HTTP extension is unavailable';
  END IF;
  job_id := cron.schedule('medithread-push-minute','* * * * *',$command$
DO $dispatch$
DECLARE
  signing_key text;
  stamp text;
  signature text;
  request_id bigint;
BEGIN
  SELECT decrypted_secret INTO STRICT signing_key
  FROM vault.decrypted_secrets WHERE name='medithread_push_dispatch_hmac';
  IF length(signing_key)<32 OR octet_length(signing_key)<>length(signing_key) THEN
    RAISE EXCEPTION 'Invalid dispatcher signing configuration';
  END IF;
  stamp := floor(extract(epoch FROM clock_timestamp()))::bigint::text;
  signature := encode(extensions.hmac(
    convert_to('POST'||chr(10)||'/internal/notifications/dispatch'||chr(10)||stamp,'UTF8'),
    convert_to(signing_key,'UTF8'),'sha256'),'hex');
  SELECT net.http_post(
    url := 'https://medithread-push-worker.vercel.app/internal/notifications/dispatch',
    body := '{}'::jsonb,
    headers := jsonb_build_object('Content-Type','application/json',
      'X-Dispatch-Timestamp',stamp,'X-Dispatch-Signature',signature),
    timeout_milliseconds := 45000) INTO request_id;
  RAISE NOTICE 'Dispatcher request ID: %', request_id;
END;
$dispatch$;
$command$);
  PERFORM cron.alter_job(job_id,active:=false);
END;
$prepare$;
COMMIT;
