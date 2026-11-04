/** Page-owned draft inputs. Never serialize Files or fields into browser storage. */
import type {EphemeralPayload,JsonValue,WorkflowView,WorkflowSourceKind} from './api/assistantWorkflows';

export type {WorkflowSourceKind} from './api/assistantWorkflows';
export interface WorkflowFile {
  upload_id:string;
  file:File;
  source_kind:WorkflowSourceKind;
  attachment_id?:string;
}
type PageTask={view:WorkflowView;fields:Record<string,JsonValue>;files:WorkflowFile[]};
function clone<T>(value:T):T{return JSON.parse(JSON.stringify(value)) as T;}

export class WorkflowMemory {
  private tasks=new Map<string,PageTask>();
  constructor(private owner:string){}
  reset(owner:string){this.tasks.clear();this.owner=owner;}
  belongsTo(owner:string){return this.owner===owner;}
  remember(view:WorkflowView){
    const previous=this.tasks.get(view.task_id);
    if(previous&&previous.view.revision>view.revision)return false;
    if(previous&&previous.view.capability_id!==view.capability_id)throw new Error('Task capability changed. Refresh this task.');
    const keepInput=view.storage_state==='save_failed'&&Object.keys(view.visible_fields).length===0&&previous;
    this.tasks.set(view.task_id,{view:clone(view),fields:clone(keepInput?previous.fields:view.input_fields??view.visible_fields),files:previous?.files??[]});
    return true;
  }
  get(task:string):WorkflowView|null{return this.tasks.has(task)?clone(this.tasks.get(task)!.view):null;}
  pagePayload(task:string):EphemeralPayload|undefined{
    const row=this.tasks.get(task);
    return row?{capability_id:row.view.capability_id,fields:clone(row.fields)}:undefined;
  }
  ephemeral(task:string):EphemeralPayload|undefined{
    return this.tasks.get(task)?.view.save_mode==='ephemeral'?this.pagePayload(task):undefined;
  }
  files(task:string):WorkflowFile[]{return (this.tasks.get(task)?.files??[]).map(row=>({...row}));}
  addFile(task:string,file:File,source_kind:WorkflowSourceKind):WorkflowFile{
    const row=this.tasks.get(task);
    if(!row)throw new Error('Open the current task before adding a photo.');
    if(file.size>8_000_000)throw new Error('Choose an image smaller than 8 MB.');
    const prior=row.files.find(item=>item.file===file&&item.source_kind===source_kind);
    if(prior)return {...prior};
    if(row.files.length>=10)throw new Error('A task can keep up to 10 photos.');
    const item={upload_id:crypto.randomUUID(),file,source_kind};row.files.push(item);return {...item};
  }
  acknowledge(task:string,upload:string,attachment:string){
    const file=this.tasks.get(task)?.files.find(item=>item.upload_id===upload);
    if(file)file.attachment_id=attachment;
  }
  revokeUploads(task:string){
    const row=this.tasks.get(task);if(row)row.files=row.files.map(({file,source_kind})=>({file,source_kind,upload_id:crypto.randomUUID()}));
  }
  discardFile(task:string,upload:string){
    const row=this.tasks.get(task);if(row)row.files=row.files.filter(item=>item.upload_id!==upload);
  }
}
