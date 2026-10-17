import type {ChatPhotoContext,ImageRoute,SourcePreview,VisualCheckResult} from './api/client';

/** Project only bounded evidence fields. Never serialize this into the patient's text. */
export function photoEvidence(route:ImageRoute,kind:ChatPhotoContext['source_kind'],source?:SourcePreview,visual?:VisualCheckResult):ChatPhotoContext {
 return {
  image_type:route.image_type,workflow:route.suggested_workflow,checked:route.checked,abstained:route.abstained,source_kind:kind,
  ...(source?{provider:source.provider.slice(0,200),extraction_model:source.extraction_model.slice(0,200)}:{}),
  products:source?.candidates.slice(0,5).map(candidate=>({
   name:candidate.product.name.slice(0,200),strength:candidate.product.strength?.slice(0,200)??null,
   printed_lines:candidate.product.source_lines.slice(0,4).map(line=>line.slice(0,400)),
   printed_directions:candidate.regimen_evidence.directions?.line.slice(0,1000)??null,
   printed_indication:candidate.regimen_evidence.indication?.line.slice(0,400)??null,
   printed_cautions:candidate.regimen_evidence.cautions?.slice(0,5).map(caution=>caution.line.slice(0,400))??[],
   instructions:candidate.regimen_evidence.instructions??null,
  }))??[],
  ...(visual?{visual:{decision:visual.decision,reason:visual.reason.slice(0,1000),count_reliable:visual.count_reliable,
   ingestion_proven:false as const,safe_to_take_confirmed:false as const,
   candidates:visual.candidates.slice(0,5).map(candidate=>({
    external_catalogue_id:candidate.external_catalogue_id.slice(0,200),display_name:candidate.display_name?.slice(0,200)??null,
    strength:candidate.strength?.slice(0,200)??null,market:candidate.market,visual_similarity:candidate.visual_similarity,
   })),
  }}:{}),
 };
}
