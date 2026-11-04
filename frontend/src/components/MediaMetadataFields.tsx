import type {GalleryImage,MedicationLibraryPdf} from '../api/client';

type Translate=(key:string)=>string;
type PdfCategory=MedicationLibraryPdf['category'];

/** Shared native/Assistant fields; this component cannot save or confirm. */
export function PhotoMetadataFields({kind,description,onKind,onDescription,t,disabled=false}:{
 kind:GalleryImage['image_kind'];description:string;onKind:(kind:GalleryImage['image_kind'])=>void;
 onDescription:(text:string)=>void;t:Translate;disabled?:boolean;
}){
 return <>
  <label className="field">{t('Photo content')}<select disabled={disabled} value={kind} onChange={event=>onKind(event.target.value as GalleryImage['image_kind'])}>
   <option value="loose_pill">{t('Loose pill')}</option><option value="blister">{t('Blister')}</option>
   <option value="package">{t('Packaging')}</option><option value="source">{t('Other or unknown')}</option>
  </select></label>
  <label className="field">{t('Photo description and source')}<input disabled={disabled} maxLength={200} value={description} onChange={event=>onDescription(event.target.value)}/></label>
 </>;
}

export function PdfMetadataFields({title,category,description,onTitle,onCategory,onDescription,t,disabled=false}:{
 title:string;category:PdfCategory;description:string;onTitle:(text:string)=>void;
 onCategory:(category:PdfCategory)=>void;onDescription:(text:string)=>void;t:Translate;disabled?:boolean;
}){
 return <>
  <label className="field">{t('File title')}<input disabled={disabled} maxLength={160} value={title} onChange={event=>onTitle(event.target.value)}/></label>
  <PdfDocumentFields category={category} description={description} onCategory={onCategory} onDescription={onDescription} t={t} disabled={disabled}/>
 </>;
}

export function PdfDocumentFields({category,description,onCategory,onDescription,t,disabled=false}:{
 category:PdfCategory;description:string;onCategory:(category:PdfCategory)=>void;
 onDescription:(text:string)=>void;t:Translate;disabled?:boolean;
}){
 return <>
  <label className="field">{t('Document category')}<select disabled={disabled} value={category} onChange={event=>onCategory(event.target.value as PdfCategory)}>
   <option value="prescription">{t('Prescription')}</option><option value="pharmacy_document">{t('Pharmacy document')}</option>
   <option value="medication_instructions">{t('Medication instructions')}</option><option value="other">{t('Other document')}</option>
  </select></label>
  <label className="field">{t('Description (optional)')}<textarea disabled={disabled} maxLength={500} value={description} onChange={event=>onDescription(event.target.value)}/></label>
 </>;
}
