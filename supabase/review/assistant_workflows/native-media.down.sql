-- REVIEW ONLY / NOT APPLIED. Never erase native facts, unknown operations or exclusions.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.assistant_native_file_intents)
 OR EXISTS(SELECT 1 FROM public.assistant_native_file_observations)
 OR EXISTS(SELECT 1 FROM public.assistant_native_media_deletions WHERE native_ticket_id IS NOT NULL) THEN
  RAISE EXCEPTION 'Nonempty native file journal; disable new entry points and retain facts/exclusions';
 END IF;
END $$;
REVOKE ALL ON FUNCTION public.assistant_native_media_command(jsonb) FROM authenticated;
DROP FUNCTION public.assistant_native_media_command(jsonb);
DROP FUNCTION assistant_evidence.record_native_media_observation(jsonb);
-- Keep proof-denying compatibility hooks. Restoring an older ACK needs separate target review.
CREATE OR REPLACE FUNCTION public.assistant_native_file_reference(p_owner uuid,p_bucket text,p_path text,p_checksum text,p_size integer) RETURNS boolean
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT false $$;
CREATE OR REPLACE FUNCTION public.assistant_native_file_ack(p_owner uuid,p_bucket text,p_path text,p_ref jsonb) RETURNS boolean
LANGUAGE sql SECURITY INVOKER SET search_path='' AS $$ SELECT false $$;
CREATE OR REPLACE FUNCTION public.ack_draft_image_cleanup(p_kind text,p_id uuid,p_path text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$ BEGIN
 RAISE EXCEPTION 'Independent native absence proof unavailable' USING ERRCODE='40001'; END $$;
CREATE OR REPLACE FUNCTION public.assistant_media_delete_current(p_owner uuid,p_action uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE r public.assistant_business_receipts%ROWTYPE;c public.assistant_media_commands%ROWTYPE;n jsonb;photo boolean;path text;bucket text;
BEGIN
 IF p_owner IS DISTINCT FROM auth.uid() THEN RAISE EXCEPTION 'Owned deletion required' USING ERRCODE='42501'; END IF;
 SELECT * INTO r FROM public.assistant_business_receipts WHERE owner=p_owner AND action_key=p_action;
 SELECT * INTO c FROM public.assistant_media_commands WHERE owner=p_owner AND action_key=p_action;
 IF r.owner IS NULL OR c.owner IS NULL OR r.outcome IS DISTINCT FROM 'applied'
 OR r.capability_id NOT IN ('gallery.photo.delete','library.pdf.delete') OR r.business_ref->>'kind' IS DISTINCT FROM 'file'
 OR c.kind IS DISTINCT FROM CASE r.capability_id WHEN 'gallery.photo.delete' THEN 'delete_photo' ELSE 'tombstone_pdf' END THEN
  RAISE EXCEPTION 'Actual confirmed native deletion receipt required' USING ERRCODE='P0002'; END IF;
 photo:=r.capability_id='gallery.photo.delete';n:=public.assistant_media_native(p_owner,photo,(r.business_ref->>'id')::uuid);
 IF n->>'deleted_at' IS NULL OR coalesce(n->'metadata_version',n->'version') IS DISTINCT FROM r.business_ref->'version'
 OR c.native_hash IS DISTINCT FROM encode(sha256(convert_to((n-'cleanup_pending')::text,'UTF8')),'hex')
 OR (photo AND n->>'source_id' IS NOT NULL) OR (NOT photo AND (n->>'source_document_id' IS NOT NULL OR n->>'regimen_version_id' IS NOT NULL)) THEN
  RAISE EXCEPTION 'Actual native tombstone changed or is protected' USING ERRCODE='40001'; END IF;
 path:=CASE WHEN photo THEN p_owner::text||'/'||(n->>'medication_id')||'/'||(n->>'checksum')||'.png'
 ELSE p_owner::text||'/library/'||(n->>'medication_id')||'/'||(n->>'checksum')||'.pdf' END;
 bucket:=CASE WHEN photo THEN 'visual-references' ELSE 'medication-sources' END;
 IF path IS NULL OR n->>'checksum' !~ '^[a-f0-9]{64}$' OR n->>'storage_path' IS DISTINCT FROM path
 OR (photo AND EXISTS(SELECT 1 FROM public.medication_images i WHERE i.patient_id=p_owner AND i.id<>(n->>'id')::uuid AND i.data->>'storage_path'=path))
 OR (NOT photo AND EXISTS(SELECT 1 FROM public.medication_library_files f WHERE f.patient_id=p_owner AND f.id<>(n->>'id')::uuid AND f.storage_path=path))
 OR EXISTS(SELECT 1 FROM public.assistant_media_copy_tickets t WHERE t.owner=p_owner AND t.bucket_id=bucket AND t.object_ref=path AND t.state<>'settled') THEN
  RAISE EXCEPTION 'Shared native reference or unresolved copy writer' USING ERRCODE='40001'; END IF;
 RETURN n;
END $$;
DROP FUNCTION public.assistant_native_file_projection(uuid);
DROP FUNCTION public.assistant_native_file_proof(uuid);
DROP FUNCTION public.assistant_native_file_delete_current(uuid,text,text);
DROP FUNCTION public.assistant_native_file_target(uuid,jsonb,boolean);
ALTER TABLE public.assistant_native_media_deletions DROP CONSTRAINT assistant_native_file_exclusion_fk;
DROP TABLE public.assistant_native_file_observations;
DROP TABLE public.assistant_native_file_intents;
DROP FUNCTION assistant_evidence.native_file_immutable();
-- Retain the exactly-one exclusion slot and existing I11 compatibility/data.
COMMIT;
