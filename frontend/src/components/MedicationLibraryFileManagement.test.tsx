// @vitest-environment jsdom
// Synthetic component tests; authenticated PostgreSQL/Storage remains separate.
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api,type MedicationLibraryFile} from '../api/client';
import {PdfUploadAction} from './MedicationLibraryFileManagement';

vi.mock('../api/client',()=>({api:{uploadLibraryPdf:vi.fn(),libraryPdf:vi.fn(),updateLibraryPdf:vi.fn(),deleteLibraryPdf:vi.fn(),manageReference:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});

const existing:MedicationLibraryFile={
 id:'DEMO-pdf',file_id:'DEMO-pdf',image_id:null,image_ids:[],name:'Medication prescription',original_filename:'prescription.pdf',
 format:'PDF',content_type:'pdf',photo_description:null,purpose_tags:['source_document'],created_at:'2026-10-19T00:00:00Z',
 eligibility:'ineligible',eligibility_reason:'not_an_image',sources:[],category:'prescription',description:'Patient supplied',version:1,byte_size:64,
};
const english=(key:string)=>key;
const chinese=(key:string)=>key==='This exact PDF already exists in your library. No duplicate file was created.'?'此 PDF 已存在，未创建重复文件。':key;

it('keeps entered metadata and consent while replacing the selected file',()=>{
 render(<PdfUploadAction medicationId="DEMO-med" medicationName="DEMO medication" files={[]} t={english} onChanged={vi.fn()} onError={vi.fn()}/>);
 const input=screen.getByLabelText('Choose a PDF file') as HTMLInputElement;
 fireEvent.change(input,{target:{files:[new File(['%PDF-1.7\n%%EOF'],'first.pdf',{type:'application/pdf'})]}});
 fireEvent.change(screen.getByLabelText('Document category'),{target:{value:'pharmacy_document'}});
 fireEvent.change(screen.getByLabelText('Description (optional)'),{target:{value:'DEMO note'}});
 fireEvent.click(screen.getByLabelText(/I agree to store this original PDF/));
 fireEvent.click(screen.getByRole('button',{name:'Replace file'}));
 fireEvent.change(input,{target:{files:[new File(['%PDF-1.7\n%%EOF'],'second.pdf',{type:'application/pdf'})]}});
 expect(screen.getByLabelText('Document category')).toHaveProperty('value','pharmacy_document');
 expect(screen.getByLabelText('Description (optional)')).toHaveProperty('value','DEMO note');
 expect(screen.getByLabelText(/I agree to store this original PDF/)).toHaveProperty('checked',true);
 expect(screen.getByText(/second\.pdf/)).toBeTruthy();
});

it('confirms cancellation after a file has been selected',()=>{
 render(<PdfUploadAction medicationId="DEMO-med" medicationName="DEMO medication" files={[]} t={english} onChanged={vi.fn()} onError={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('Choose a PDF file'),{target:{files:[new File(['%PDF-1.7\n%%EOF'],'selected.pdf',{type:'application/pdf'})]}});
 fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
 expect(screen.getByRole('alertdialog').textContent).toContain('Discard this unsaved PDF upload?');
 fireEvent.click(screen.getByRole('button',{name:'Keep editing'}));
 expect(screen.getByText(/selected\.pdf/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
 fireEvent.click(screen.getByRole('button',{name:'Discard changes'}));
 expect(screen.queryByRole('dialog')).toBeNull();
});

it('reports an exact duplicate in Chinese and offers the existing file',async()=>{
 vi.mocked(api.uploadLibraryPdf).mockResolvedValue({file:{...existing,duplicate:undefined} as never,duplicate:true});
 render(<PdfUploadAction medicationId="DEMO-med" medicationName="DEMO medication" files={[existing]} t={chinese} onChanged={vi.fn()} onError={vi.fn()}/>);
 const input=screen.getByLabelText('Choose a PDF file') as HTMLInputElement;
 fireEvent.change(input,{target:{files:[new File(['%PDF-1.7\n%%EOF'],'duplicate.pdf',{type:'application/pdf'})]}});
 fireEvent.click(screen.getByLabelText(/I agree to store this original PDF/));
 fireEvent.click(screen.getByRole('button',{name:'Save PDF'}));
 await waitFor(()=>expect(screen.getByText('此 PDF 已存在，未创建重复文件。')).toBeTruthy());
 expect(screen.getByRole('button',{name:'Preview PDF: Medication prescription'})).toBeTruthy();
 expect(screen.getByText('Choose another PDF to replace this selection.')).toBeTruthy();
});
