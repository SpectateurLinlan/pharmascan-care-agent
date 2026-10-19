-- Patient-owned PDF library files and auditable gallery-photo lifecycle.
-- Files are stored only in the existing private medication-sources bucket.
BEGIN;
SET LOCAL search_path = pg_catalog, public;

CREATE TABLE public.medication_library_files (
    id uuid PRIMARY KEY,
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    medication_id uuid NOT NULL,
    source_document_id uuid,
    regimen_version_id uuid,
    storage_path text NOT NULL,
    checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    original_filename text NOT NULL CHECK (length(btrim(original_filename)) BETWEEN 1 AND 240),
    display_title text NOT NULL CHECK (length(btrim(display_title)) BETWEEN 1 AND 160),
    category text NOT NULL CHECK (category IN ('prescription','pharmacy_document','medication_instructions','other')),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 500),
    content_type text NOT NULL DEFAULT 'application/pdf' CHECK (content_type = 'application/pdf'),
    byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 10485760),
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    deleted_at timestamptz,
    cleanup_pending boolean NOT NULL DEFAULT false,
    demo_only boolean NOT NULL DEFAULT false,
    UNIQUE (patient_id, id),
    UNIQUE (patient_id, medication_id, checksum),
    UNIQUE (storage_path),
    FOREIGN KEY (patient_id, medication_id)
      REFERENCES public.patient_medications(patient_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, source_document_id)
      REFERENCES public.source_documents(patient_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (patient_id, regimen_version_id)
      REFERENCES public.regimen_versions(patient_id,id) ON DELETE RESTRICT,
    CHECK (storage_path LIKE patient_id::text || '/library/%' AND position('..' in storage_path)=0)
);
CREATE INDEX medication_library_files_owner_medication_idx
  ON public.medication_library_files(patient_id, medication_id, uploaded_at DESC)
  WHERE deleted_at IS NULL;

CREATE TABLE public.medication_library_file_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES public.patient_profiles(user_id) ON DELETE RESTRICT,
    file_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('uploaded','metadata_updated','deleted')),
    before_values jsonb,
    after_values jsonb,
    actor_id uuid NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id,id),
    FOREIGN KEY (patient_id,file_id)
      REFERENCES public.medication_library_files(patient_id,id) ON DELETE RESTRICT,
    CHECK (actor_id=patient_id)
);
ALTER TABLE public.medication_library_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_library_files FORCE ROW LEVEL SECURITY;
CREATE POLICY medication_library_files_owner_read ON public.medication_library_files
  FOR SELECT TO authenticated USING (patient_id=(SELECT auth.uid()));
ALTER TABLE public.medication_library_file_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_library_file_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY medication_library_file_audit_owner_read ON public.medication_library_file_audit
  FOR SELECT TO authenticated USING (patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.medication_library_files, public.medication_library_file_audit
  FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.medication_library_files, public.medication_library_file_audit TO authenticated;

CREATE FUNCTION public.register_medication_library_pdf(p_file jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE o uuid:=auth.uid(); inserted public.medication_library_files%ROWTYPE; existing public.medication_library_files%ROWTYPE;
BEGIN
 IF o IS NULL OR jsonb_typeof(p_file)<>'object' THEN
   RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Authenticated file registration required'; END IF;
 IF p_file->>'patient_id' IS DISTINCT FROM o::text OR p_file->>'content_type' IS DISTINCT FROM 'application/pdf'
    OR p_file->>'category' NOT IN ('prescription','pharmacy_document','medication_instructions','other') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid medication file metadata'; END IF;
 INSERT INTO public.medication_library_files
  (id,patient_id,medication_id,storage_path,checksum,original_filename,display_title,category,description,content_type,byte_size,demo_only)
 VALUES ((p_file->>'id')::uuid,o,(p_file->>'medication_id')::uuid,p_file->>'storage_path',p_file->>'checksum',
   p_file->>'original_filename',p_file->>'display_title',p_file->>'category',coalesce(p_file->>'description',''),
   'application/pdf',(p_file->>'byte_size')::integer,false)
 ON CONFLICT (patient_id,medication_id,checksum) DO NOTHING RETURNING * INTO inserted;
 IF FOUND THEN
  INSERT INTO public.medication_library_file_audit(patient_id,file_id,action,after_values,actor_id)
   VALUES(o,inserted.id,'uploaded',jsonb_build_object('medication_id',inserted.medication_id,'category',inserted.category,'byte_size',inserted.byte_size),o);
  RETURN jsonb_build_object('file',to_jsonb(inserted),'duplicate',false);
 END IF;
 SELECT * INTO existing FROM public.medication_library_files WHERE patient_id=o
  AND medication_id=(p_file->>'medication_id')::uuid AND checksum=p_file->>'checksum';
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='Retry file registration'; END IF;
 RETURN jsonb_build_object('file',to_jsonb(existing),'duplicate',true);
END $$;

CREATE FUNCTION public.update_medication_library_pdf(p_id uuid,p_expected_version integer,p_title text,p_category text,p_description text)
RETURNS public.medication_library_files LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE o uuid:=auth.uid(); old_row public.medication_library_files%ROWTYPE; new_row public.medication_library_files%ROWTYPE;
BEGIN
 IF o IS NULL THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Authentication required'; END IF;
 SELECT * INTO old_row FROM public.medication_library_files WHERE patient_id=o AND id=p_id FOR UPDATE;
 IF NOT FOUND OR old_row.deleted_at IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='P7504',MESSAGE='File not found'; END IF;
 IF p_expected_version IS NULL OR old_row.version<>p_expected_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='File changed; reload before editing'; END IF;
 IF length(btrim(p_title)) NOT BETWEEN 1 AND 160 OR p_category NOT IN ('prescription','pharmacy_document','medication_instructions','other') OR length(p_description)>500 THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid file metadata'; END IF;
 UPDATE public.medication_library_files SET display_title=p_title,category=p_category,description=p_description,version=version+1
  WHERE patient_id=o AND id=p_id RETURNING * INTO new_row;
 INSERT INTO public.medication_library_file_audit(patient_id,file_id,action,before_values,after_values,actor_id)
  VALUES(o,p_id,'metadata_updated',jsonb_build_object('display_title',old_row.display_title,'category',old_row.category,'description',old_row.description),
   jsonb_build_object('display_title',new_row.display_title,'category',new_row.category,'description',new_row.description),o);
 RETURN new_row;
END $$;

CREATE FUNCTION public.tombstone_medication_library_pdf(p_id uuid,p_confirmed boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE o uuid:=auth.uid(); row_data public.medication_library_files%ROWTYPE;
BEGIN
 IF o IS NULL OR p_confirmed IS DISTINCT FROM true THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Explicit confirmation required'; END IF;
 SELECT * INTO row_data FROM public.medication_library_files WHERE patient_id=o AND id=p_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P7504',MESSAGE='File not found'; END IF;
 IF row_data.source_document_id IS NOT NULL OR row_data.regimen_version_id IS NOT NULL THEN
  RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='File is linked to a protected source or regimen'; END IF;
 IF row_data.deleted_at IS NULL THEN
  UPDATE public.medication_library_files SET deleted_at=now(),cleanup_pending=true,version=version+1
   WHERE patient_id=o AND id=p_id RETURNING * INTO row_data;
  INSERT INTO public.medication_library_file_audit(patient_id,file_id,action,before_values,after_values,actor_id)
   VALUES(o,p_id,'deleted',jsonb_build_object('deleted_at',null),jsonb_build_object('deleted_at',row_data.deleted_at),o);
 END IF;
 RETURN jsonb_build_object('deleted',true,'cleanup_pending',row_data.cleanup_pending,'storage_path',row_data.storage_path);
END $$;

CREATE FUNCTION public.ack_medication_library_pdf_cleanup(p_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 UPDATE public.medication_library_files SET cleanup_pending=false
 WHERE patient_id=auth.uid() AND id=p_id AND deleted_at IS NOT NULL;
END $$;

-- Photo lifecycle writes go through this owner-checked, versioned, audited RPC.
CREATE TABLE public.medication_image_audit (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), patient_id uuid NOT NULL,
 image_id uuid NOT NULL, action text NOT NULL CHECK(action IN ('metadata_updated','removed_from_gallery','deleted','stopped_comparison')),
 before_values jsonb NOT NULL, after_values jsonb NOT NULL, actor_id uuid NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(patient_id,image_id) REFERENCES public.medication_images(patient_id,id) ON DELETE RESTRICT,
 CHECK(actor_id=patient_id)
);
ALTER TABLE public.medication_image_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medication_image_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY medication_image_audit_owner_read ON public.medication_image_audit
 FOR SELECT TO authenticated USING(patient_id=(SELECT auth.uid()));
REVOKE ALL ON public.medication_image_audit FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.medication_image_audit TO authenticated;

-- Serialize new references with object retirement. No new row may attach to a
-- tombstoned object while the application is cleaning up its private bytes.
CREATE INDEX medication_images_storage_reference_idx ON public.medication_images ((data->>'storage_path'));
CREATE FUNCTION public.guard_gallery_image_storage_reference() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE object_path text:=NEW.data->>'storage_path';
BEGIN
 IF object_path IS NULL OR object_path NOT LIKE NEW.patient_id::text || '/%'
   OR position('..' in object_path)>0 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid private image path'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(object_path,0));
 IF EXISTS(SELECT 1 FROM public.medication_images WHERE data->>'storage_path'=object_path
   AND data->>'deleted_at' IS NOT NULL) THEN
  RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='Removed photo cannot acquire new associations'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER gallery_image_storage_reference_guard BEFORE INSERT ON public.medication_images
 FOR EACH ROW EXECUTE FUNCTION public.guard_gallery_image_storage_reference();
REVOKE ALL ON FUNCTION public.guard_gallery_image_storage_reference() FROM PUBLIC,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION public.guard_reference_retirement() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE old_data jsonb:=OLD.data; new_data jsonb:=NEW.data;
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.patient_id IS DISTINCT FROM OLD.patient_id
  OR NEW.medication_id IS DISTINCT FROM OLD.medication_id OR NEW.source_id IS DISTINCT FROM OLD.source_id
  OR NEW.created_at IS DISTINCT FROM OLD.created_at
  OR NEW.data->>'checksum' IS DISTINCT FROM OLD.data->>'checksum'
  OR NEW.data->>'storage_path' IS DISTINCT FROM OLD.data->>'storage_path' THEN RAISE EXCEPTION 'Protected image identity cannot change'; END IF;
 IF (new_data - 'eligibility' - 'eligibility_reason') IS NOT DISTINCT FROM (old_data - 'eligibility' - 'eligibility_reason')
   AND (new_data->>'eligibility') IS NOT DISTINCT FROM 'ineligible'
   AND (new_data->>'eligibility_reason') IS NOT DISTINCT FROM 'patient_retired_reference' THEN RETURN NEW; END IF;
 IF old_data->>'deleted_at' IS NOT NULL
   AND coalesce((old_data->>'cleanup_pending')::boolean,false)
   AND NOT coalesce((new_data->>'cleanup_pending')::boolean,false)
   AND (new_data - 'cleanup_pending' - 'metadata_version') IS NOT DISTINCT FROM (old_data - 'cleanup_pending' - 'metadata_version')
   AND new_data->>'metadata_version' IS NOT DISTINCT FROM old_data->>'metadata_version' THEN RETURN NEW; END IF;
 IF (new_data - 'image_kind' - 'source_description' - 'metadata_version' - 'gallery_removed' - 'deleted_at' - 'cleanup_pending' - 'eligibility' - 'eligibility_reason')
   IS DISTINCT FROM (old_data - 'image_kind' - 'source_description' - 'metadata_version' - 'gallery_removed' - 'deleted_at' - 'cleanup_pending' - 'eligibility' - 'eligibility_reason') THEN
   RAISE EXCEPTION 'Unsupported image metadata mutation'; END IF;
 IF coalesce((new_data->>'metadata_version')::integer,1) <> coalesce((old_data->>'metadata_version')::integer,1)+1 THEN
   RAISE EXCEPTION 'Image metadata version must increment'; END IF;
 IF new_data->>'image_kind' NOT IN ('loose_pill','package','blister','source') OR length(new_data->>'source_description') NOT BETWEEN 1 AND 200 THEN
   RAISE EXCEPTION 'Invalid image metadata'; END IF;
 IF (new_data->>'image_kind') IS DISTINCT FROM (old_data->>'image_kind') THEN
   new_data:=jsonb_set(jsonb_set(new_data,'{eligibility}','"ineligible"'),'{eligibility_reason}','"patient_metadata_changed"');
 END IF;
 NEW.data:=new_data;
 RETURN NEW;
END $$;
REVOKE UPDATE(data) ON public.medication_images FROM authenticated;

CREATE FUNCTION public.manage_personal_gallery_image(p_image_id uuid,p_action text,p_expected_version integer,
 p_image_kind text DEFAULT NULL,p_source_description text DEFAULT NULL,p_confirmed boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE o uuid:=auth.uid(); old_row public.medication_images%ROWTYPE; new_data jsonb; protected boolean;
BEGIN
 IF o IS NULL OR p_action IS NULL OR p_action NOT IN ('edit','remove','delete') THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Authenticated image action required'; END IF;
 SELECT * INTO old_row FROM public.medication_images WHERE patient_id=o AND id=p_image_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P7504',MESSAGE='Photo not found'; END IF;
 IF old_row.data->>'deleted_at' IS NOT NULL THEN
  IF p_action='delete' AND p_confirmed IS TRUE THEN RETURN jsonb_build_object('image',old_row.data,'storage_path',old_row.data->>'storage_path','cleanup_pending',coalesce((old_row.data->>'cleanup_pending')::boolean,false)); END IF;
  RAISE EXCEPTION USING ERRCODE='P7504',MESSAGE='Photo not found';
 END IF;
 IF p_expected_version IS NULL OR coalesce((old_row.data->>'metadata_version')::integer,1)<>p_expected_version THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='Photo changed; reload before editing'; END IF;
 IF p_action IN ('remove','delete') AND p_confirmed IS DISTINCT FROM true THEN RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Explicit confirmation required'; END IF;
 IF p_action IN ('remove','delete') AND old_row.source_id IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='Source-linked evidence cannot be removed or deleted'; END IF;
 IF p_action='delete' THEN PERFORM pg_advisory_xact_lock(hashtextextended(old_row.data->>'storage_path',0)); END IF;
 SELECT EXISTS(SELECT 1 FROM public.medication_images i WHERE i.data->>'storage_path'=old_row.data->>'storage_path' AND (i.patient_id,i.id)<>(old_row.patient_id,old_row.id)) INTO protected;
 IF protected AND p_action='delete' THEN RAISE EXCEPTION USING ERRCODE='P7502',MESSAGE='Shared photo cannot be deleted'; END IF;
 new_data:=old_row.data;
 IF p_action='edit' THEN
  IF p_image_kind IS NULL OR p_image_kind NOT IN ('loose_pill','package','blister','source') OR p_source_description IS NULL OR length(btrim(p_source_description)) NOT BETWEEN 1 AND 200 THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='Invalid photo metadata'; END IF;
  new_data:=jsonb_set(jsonb_set(new_data,'{image_kind}',to_jsonb(p_image_kind)),'{source_description}',to_jsonb(p_source_description));
  IF p_image_kind IS DISTINCT FROM old_row.data->>'image_kind' THEN
   new_data:=jsonb_set(jsonb_set(new_data,'{eligibility}','"ineligible"'),'{eligibility_reason}','"patient_metadata_changed"');
  END IF;
  new_data:=jsonb_set(new_data,'{metadata_version}',to_jsonb(p_expected_version+1));
 ELSIF p_action='remove' THEN
  new_data:=jsonb_set(jsonb_set(new_data,'{gallery_removed}','true'),'{metadata_version}',to_jsonb(p_expected_version+1));
  new_data:=jsonb_set(jsonb_set(new_data,'{eligibility}','"ineligible"'),'{eligibility_reason}','"patient_removed_from_gallery"');
 ELSIF p_action='delete' THEN
  new_data:=jsonb_set(jsonb_set(jsonb_set(new_data,'{deleted_at}',to_jsonb(now())),'{cleanup_pending}','true'),'{metadata_version}',to_jsonb(p_expected_version+1));
  new_data:=jsonb_set(jsonb_set(new_data,'{eligibility}','"ineligible"'),'{eligibility_reason}','"patient_deleted_photo"');
 END IF;
 UPDATE public.medication_images SET data=new_data WHERE patient_id=o AND id=p_image_id;
 IF p_action IN ('remove','delete') OR p_image_kind IS DISTINCT FROM old_row.data->>'image_kind' THEN
   DELETE FROM public.image_embeddings WHERE patient_id=o AND image_id=p_image_id;
 END IF;
 INSERT INTO public.medication_image_audit(patient_id,image_id,action,before_values,after_values,actor_id)
 VALUES(o,p_image_id,CASE p_action WHEN 'edit' THEN 'metadata_updated' WHEN 'remove' THEN 'removed_from_gallery' ELSE 'deleted' END,
   jsonb_build_object('image_kind',old_row.data->'image_kind','source_description',old_row.data->'source_description','eligibility',old_row.data->'eligibility'),
   jsonb_build_object('image_kind',new_data->'image_kind','source_description',new_data->'source_description','eligibility',new_data->'eligibility','gallery_removed',new_data->'gallery_removed','deleted_at',new_data->'deleted_at'),o);
 RETURN jsonb_build_object('image',new_data,'storage_path',old_row.data->>'storage_path','cleanup_pending',p_action='delete');
END $$;

CREATE FUNCTION public.ack_personal_gallery_image_cleanup(p_image_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 UPDATE public.medication_images SET data=jsonb_set(data,'{cleanup_pending}','false')
 WHERE patient_id=auth.uid() AND id=p_image_id AND data->>'deleted_at' IS NOT NULL;
END $$;

CREATE OR REPLACE FUNCTION public.retire_personal_reference(p_image_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE old_data jsonb; result jsonb;
BEGIN
 SELECT data INTO old_data FROM public.medication_images
 WHERE id=p_image_id AND patient_id=auth.uid() FOR UPDATE;
 IF old_data IS NULL THEN RAISE EXCEPTION USING ERRCODE='P7504',MESSAGE='Owned reference not found'; END IF;
 IF old_data->>'eligibility' IS DISTINCT FROM 'eligible' THEN RETURN old_data; END IF;
 UPDATE public.medication_images SET data=jsonb_set(jsonb_set(data,'{eligibility}','"ineligible"'),'{eligibility_reason}','"patient_retired_reference"')
 WHERE id=p_image_id AND patient_id=auth.uid() AND data->>'deleted_at' IS NULL AND coalesce(data->>'gallery_removed','false')='false'
 RETURNING data INTO result;
 IF result IS NULL THEN RAISE EXCEPTION USING ERRCODE='P7504',MESSAGE='Owned reference not found'; END IF;
 DELETE FROM public.image_embeddings WHERE patient_id=auth.uid() AND image_id=p_image_id;
 INSERT INTO public.medication_image_audit(patient_id,image_id,action,before_values,after_values,actor_id)
 VALUES(auth.uid(),p_image_id,'stopped_comparison',jsonb_build_object('eligibility',old_data->'eligibility','eligibility_reason',old_data->'eligibility_reason'),
  jsonb_build_object('eligibility',result->'eligibility','eligibility_reason',result->'eligibility_reason'),auth.uid());
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION public.register_medication_library_pdf(jsonb),public.update_medication_library_pdf(uuid,integer,text,text,text),
 public.tombstone_medication_library_pdf(uuid,boolean),public.ack_medication_library_pdf_cleanup(uuid),
 public.manage_personal_gallery_image(uuid,text,integer,text,text,boolean),public.ack_personal_gallery_image_cleanup(uuid) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.register_medication_library_pdf(jsonb),public.update_medication_library_pdf(uuid,integer,text,text,text),
 public.tombstone_medication_library_pdf(uuid,boolean),public.ack_medication_library_pdf_cleanup(uuid),
 public.manage_personal_gallery_image(uuid,text,integer,text,text,boolean),public.ack_personal_gallery_image_cleanup(uuid) TO authenticated;
REVOKE ALL ON FUNCTION public.retire_personal_reference(uuid) FROM PUBLIC,anon,service_role;
GRANT EXECUTE ON FUNCTION public.retire_personal_reference(uuid) TO authenticated;
NOTIFY pgrst,'reload schema';
COMMIT;
