// @vitest-environment jsdom
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {LanguageProvider, useLanguage} from '../language';
import {TextSizeSlider} from './TextSizeSlider';
import {api, type PatientPreferences} from '../api/client';
vi.mock('../api/client',()=>({api:{preferences:vi.fn(),updatePreferences:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const profile:PatientPreferences={patient_id:'DEMO',preferred_language:'en',speech_locale:'en-SG',text_size:'standard',text_scale_percent:100,voice_enabled:true,tts_autoplay:false,reminder_lead_minutes:0,timezone:'Asia/Singapore',created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z'};
it('previews root-wide scaling and saves once on release, preserving the numeric value',async()=>{
  vi.mocked(api.updatePreferences).mockResolvedValue({...profile,text_scale_percent:137,text_size:'large'});
  render(<LanguageProvider><TextSizeSlider/></LanguageProvider>);
  const slider=screen.getByRole('slider',{name:/Text size/});
  fireEvent.change(slider,{target:{value:'137'}});
  expect(document.documentElement.style.getPropertyValue('--font-scale')).toBe('1.37');
  expect(screen.getByText('137%')).toBeTruthy();expect(api.updatePreferences).not.toHaveBeenCalled();
  fireEvent.pointerUp(slider);fireEvent.blur(slider);
  await waitFor(()=>expect(api.updatePreferences).toHaveBeenCalledExactlyOnceWith({text_scale_percent:137}));
  expect(document.documentElement.style.getPropertyValue('--font-scale')).toBe('1.37');
});
it('reloads saved scale and reverts the preview on failed save',async()=>{
  vi.mocked(api.preferences).mockResolvedValue({...profile,text_scale_percent:129});
  vi.mocked(api.updatePreferences).mockRejectedValue(new Error('SIMULATED failure'));
  function Loaded(){const {loadPreferences,preferenceError}=useLanguage();return <><button onClick={()=>void loadPreferences()}>Reload</button><TextSizeSlider/><p>{preferenceError}</p></>;}
  render(<LanguageProvider><Loaded/></LanguageProvider>);fireEvent.click(screen.getByText('Reload'));
  await screen.findByText('129%');const slider=screen.getByRole('slider',{name:/Text size/});
  fireEvent.change(slider,{target:{value:'150'}});fireEvent.keyUp(slider,{key:'ArrowRight'});
  await screen.findByText(/Could not save preferences/);
  expect(document.documentElement.style.getPropertyValue('--font-scale')).toBe('1.29');
});
