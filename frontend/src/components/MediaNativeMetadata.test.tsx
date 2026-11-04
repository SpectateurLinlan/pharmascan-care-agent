// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api,type GalleryImage,type MedicationLibraryFile} from '../api/client';
import {PhotoLifecycleActions,PdfFileCard} from './MedicationLibraryFileManagement';
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
const t=(text:string)=>text;

it('preserves the native photo edit fields and original unbound request',async()=>{
 const photo={id:'DEMO-image',image_kind:'package',source_description:'DEMO original',metadata_version:3} as GalleryImage;
 const write=vi.spyOn(api,'manageReference').mockResolvedValue(photo),changed=vi.fn();
 render(<PhotoLifecycleActions photo={photo} t={t} onChanged={changed} onError={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Edit Photo Information'}));
 fireEvent.change(screen.getByLabelText('Photo content'),{target:{value:'blister'}});
 fireEvent.change(screen.getByLabelText('Photo description and source'),{target:{value:'DEMO amended'}});
 fireEvent.click(screen.getByRole('button',{name:'Save changes'}));
 await waitFor(()=>expect(write).toHaveBeenCalledWith(photo.id,{action:'edit',expected_version:3,image_kind:'blister',source_description:'DEMO amended'}));
 expect(changed).toHaveBeenCalledTimes(1);
});

it('preserves the native PDF edit fields and original unbound request',async()=>{
 vi.stubGlobal('URL',class extends URL {static createObjectURL(){return 'blob:DEMO-native';}static revokeObjectURL(){}});
 vi.spyOn(api,'libraryPdf').mockResolvedValue(new Blob(['DEMO'],{type:'application/pdf'}));
 const file={id:'DEMO-file',file_id:'DEMO-file',name:'DEMO original',original_filename:'DEMO.pdf',category:'other',description:'DEMO old note',created_at:'2026-10-01T00:00:00Z',version:4,byte_size:42} as MedicationLibraryFile;
 const write=vi.spyOn(api,'updateLibraryPdf').mockResolvedValue({display_title:'DEMO amended',category:'other',description:'DEMO amended note'} as never);
 render(<PdfFileCard file={file} t={t} onChanged={vi.fn()} onError={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Preview PDF: DEMO original'}));
 fireEvent.click(screen.getByRole('button',{name:'Edit File Information'}));
 fireEvent.change(screen.getByLabelText('File title'),{target:{value:'DEMO amended'}});
 fireEvent.change(screen.getByLabelText('Description (optional)'),{target:{value:'DEMO amended note'}});
 fireEvent.click(screen.getByRole('button',{name:'Save changes'}));
 await waitFor(()=>expect(write).toHaveBeenCalledWith(file.file_id,{expected_version:4,title:'DEMO amended',category:'other',description:'DEMO amended note'}));
});
