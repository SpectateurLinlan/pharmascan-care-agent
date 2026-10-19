// @vitest-environment jsdom
import {afterEach,it,expect,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {PhotoAcquisition} from './PhotoAcquisition';

afterEach(()=>{cleanup();vi.restoreAllMocks();});

function secureContext(value=true){Object.defineProperty(window,'isSecureContext',{configurable:true,value});}
function camera(getUserMedia:ReturnType<typeof vi.fn>){
 secureContext();Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia}});
 Object.defineProperty(navigator,'permissions',{configurable:true,value:{query:vi.fn().mockResolvedValue({state:'prompt'})}});
 vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue(undefined);
}

it('offers camera and file selection, reports a prior permission denial, and leaves file choice explicit',async()=>{
 const getUserMedia=vi.fn().mockRejectedValue(new DOMException('denied','NotAllowedError'));camera(getUserMedia);
 render(<PhotoAcquisition file={null} onFile={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Take photo'}));
 expect((await screen.findByRole('alert')).textContent).toContain('If access was previously denied');
 expect(getUserMedia).toHaveBeenCalledOnce();expect(screen.getByRole('button',{name:'Choose existing photo'})).toBeTruthy();
});

it.each([
 ['NotFoundError','No camera was found'],
 ['NotReadableError','camera is in use or could not be read'],
 ['AbortError','camera is in use or could not be read'],
 ['OtherError','Camera could not be started'],
])('distinguishes camera failure %s',async(name,message)=>{
 camera(vi.fn().mockRejectedValue(new DOMException('failed',name)));
 render(<PhotoAcquisition file={null} onFile={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'Take photo'}));
 expect((await screen.findByRole('alert')).textContent).toContain(message);
});

it('reports insecure context and unsupported browser without requesting a camera',async()=>{
 const getUserMedia=vi.fn();camera(getUserMedia);secureContext(false);
 const {rerender}=render(<PhotoAcquisition file={null} onFile={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'Take photo'}));
 expect((await screen.findByRole('alert')).textContent).toContain('secure connection');expect(getUserMedia).not.toHaveBeenCalled();
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:undefined});secureContext(true);rerender(<PhotoAcquisition file={null} onFile={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Take photo'}));expect((await screen.findByRole('alert')).textContent).toContain('not supported in this browser');
});

it('shows preview, captures a validated image, and stops tracks without saving it',async()=>{
 const stop=vi.fn(),onFile=vi.fn();const stream={getTracks:()=>[{stop}]} as unknown as MediaStream;
 const getUserMedia=vi.fn().mockResolvedValue(stream);camera(getUserMedia);
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D);
 vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(callback=>callback(new Blob(['DEMO_ONLY capture'],{type:'image/jpeg'})));
 render(<PhotoAcquisition file={null} onFile={onFile}/>);fireEvent.click(screen.getByRole('button',{name:'Take photo'}));
 const video=await screen.findByLabelText('Camera preview');expect(video).toBeTruthy();
 Object.defineProperty(video,'videoWidth',{configurable:true,value:640});Object.defineProperty(video,'videoHeight',{configurable:true,value:480});
 fireEvent.click(screen.getByRole('button',{name:'Capture photo'}));
 await waitFor(()=>expect(onFile).toHaveBeenCalledOnce());expect(onFile.mock.calls[0]![0]).toMatchObject({type:'image/jpeg',name:'medication-photo.jpg'});expect(stop).toHaveBeenCalledOnce();
});

it('stops camera tracks on cancellation and on unmount',async()=>{
 const stop=vi.fn(),stream={getTracks:()=>[{stop}]} as unknown as MediaStream;camera(vi.fn().mockResolvedValue(stream));
 const view=render(<PhotoAcquisition file={null} onFile={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'Take photo'}));
 await waitFor(()=>expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledOnce());fireEvent.click(await screen.findByRole('button',{name:'Cancel camera'}));expect(stop).toHaveBeenCalledOnce();
 const second={getTracks:()=>[{stop}]} as unknown as MediaStream;vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce(second);fireEvent.click(screen.getByRole('button',{name:'Take photo'}));await waitFor(()=>expect(screen.getByLabelText('Camera preview')).toBeTruthy());view.unmount();expect(stop).toHaveBeenCalledTimes(2);
});
