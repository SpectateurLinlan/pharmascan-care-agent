// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {api,type PatientPreferences} from '../api/client';
import {LanguageProvider} from '../language';
import {LanguageMenu} from './LanguageMenu';

vi.mock('../api/client',()=>({api:{updatePreferences:vi.fn()}}));

const preference=(language:'en'|'zh'):PatientPreferences=>({
 patient_id:'DEMO-owner',preferred_language:language,speech_locale:language==='zh'?'zh-CN':'en-SG',
 text_size:'standard',voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,
 timezone:'Asia/Singapore',created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z',
});

beforeEach(()=>vi.resetAllMocks());
afterEach(()=>{cleanup();vi.restoreAllMocks();});

it('switches between English and Chinese with one click and persists each choice',async()=>{
 let finishChinese!:(value:PatientPreferences)=>void;
 let finishEnglish!:(value:PatientPreferences)=>void;
 vi.mocked(api.updatePreferences)
  .mockReturnValueOnce(new Promise(resolve=>{finishChinese=resolve;}))
  .mockReturnValueOnce(new Promise(resolve=>{finishEnglish=resolve;}));
 render(<LanguageProvider><LanguageMenu/></LanguageProvider>);
 const control=screen.getByRole('button',{name:'Switch language'});
 expect(control.textContent).toBe('中文');
 fireEvent.click(control);
 const pending=screen.getByRole('button',{name:'正在切换为中文…'});
 expect((pending as HTMLButtonElement).disabled).toBe(true);expect(pending.getAttribute('aria-busy')).toBe('true');
 expect(screen.getByRole('status').textContent).toBe('正在切换为中文…');
 expect(pending.textContent).toBe('EN');
 fireEvent.click(pending);
 expect(api.updatePreferences).toHaveBeenCalledOnce();
 finishChinese(preference('zh'));
 await waitFor(()=>expect(screen.getByRole('button',{name:'切换语言'}).textContent).toBe('EN'));
 expect(api.updatePreferences).toHaveBeenNthCalledWith(1,{preferred_language:'zh'});
 expect(screen.queryByRole('menu')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'切换语言'}));
 const pendingEnglish=screen.getByRole('button',{name:'Switching to English…'});
 expect((pendingEnglish as HTMLButtonElement).disabled).toBe(true);
 expect(screen.getByRole('status').textContent).toBe('Switching to English…');
 finishEnglish(preference('en'));
 await waitFor(()=>expect(screen.getByRole('button',{name:'Switch language'}).textContent).toBe('中文'));
 expect(api.updatePreferences).toHaveBeenNthCalledWith(2,{preferred_language:'en'});
});

it('restores the saved language and reports failure when persistence fails',async()=>{
 let reject!:(error:Error)=>void;
 vi.mocked(api.updatePreferences).mockReturnValue(new Promise((_,failed)=>{reject=failed;}));
 render(<LanguageProvider><LanguageMenu/></LanguageProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Switch language'}));
 expect(screen.getByRole('button',{name:'正在切换为中文…'}).textContent).toBe('EN');
 reject(new Error('DEMO unavailable'));
 await waitFor(()=>expect(screen.getByRole('button',{name:'Switch language'}).textContent).toBe('中文'));
});
