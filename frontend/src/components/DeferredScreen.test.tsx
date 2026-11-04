// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {deferScreen} from './DeferredScreen';

afterEach(cleanup);
it('keeps the shell visible while an unopened section loads',async()=>{
 let resolve!:(module:{default:()=>React.ReactNode})=>void;
 const Deferred=deferScreen(()=>new Promise<{default:()=>React.ReactNode}>(done=>{resolve=done;}));
 render(<><h1>DEMO shell</h1><Deferred/></>);
 expect(screen.getByRole('heading',{name:'DEMO shell'})).toBeTruthy();
 expect(screen.getByRole('status')).toBeTruthy();
 await act(async()=>{resolve({default:()=> <p>DEMO section</p>});});
 expect(await screen.findByText('DEMO section')).toBeTruthy();
});
it('offers a fresh module load after a failed download',async()=>{
 const load=vi.fn().mockRejectedValueOnce(new Error('DEMO download failed')).mockResolvedValueOnce({default:()=> <p>DEMO recovered</p>});
 const Deferred=deferScreen(load);
 const consoleError=vi.spyOn(console,'error').mockImplementation(()=>undefined);
 try{
  render(<Deferred/>);
  expect(await screen.findByRole('alert')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Retry loading section'}));
  expect(await screen.findByText('DEMO recovered')).toBeTruthy();
  expect(load).toHaveBeenCalledTimes(2);
 }finally{consoleError.mockRestore();}
});
