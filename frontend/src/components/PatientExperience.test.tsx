// @vitest-environment jsdom
import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {accountDisplayName} from '../accountPresentation';
import {useImageConsent} from '../imageConsent';
import {ErrorNotice} from './primitives';
import {ApiError} from '../api/client';

afterEach(()=>{cleanup();localStorage.clear();});
it('uses the member email prefix instead of an inherited guest placeholder',()=>{
 const member={kind:'member',email:'DEMO-person@example.test',verified:true} as const;
 expect(accountDisplayName(member,'Guest')).toBe('DEMO-person');
 expect(accountDisplayName(member,'My preferred name')).toBe('My preferred name');
 expect(accountDisplayName({kind:'guest',email:null,verified:false},'Other patient')).toBe('Guest');
});
it('remembers explicit permission for one owner and allows revocation without leaking it to another',()=>{
 function Permission({owner}:{owner:string}){const [allowed,change]=useImageConsent(owner);return <label>Photo processing<input type="checkbox" checked={allowed} onChange={event=>change(event.target.checked)}/></label>;}
 const view=render(<Permission owner="DEMO-A"/>);expect(screen.getByRole('checkbox')).toHaveProperty('checked',false);
 fireEvent.click(screen.getByRole('checkbox'));expect(screen.getByRole('checkbox')).toHaveProperty('checked',true);
 view.rerender(<Permission owner="DEMO-B"/>);expect(screen.getByRole('checkbox')).toHaveProperty('checked',false);
 view.rerender(<Permission owner="DEMO-A"/>);expect(screen.getByRole('checkbox')).toHaveProperty('checked',true);
 localStorage.removeItem('pharmascan.image-processing.v1.DEMO-A');
 fireEvent(window,new StorageEvent('storage',{key:'pharmascan.image-processing.v1.DEMO-A'}));
 expect(screen.getByRole('checkbox')).toHaveProperty('checked',false);
 fireEvent.click(screen.getByRole('checkbox'));
 fireEvent.click(screen.getByRole('checkbox'));view.unmount();render(<Permission owner="DEMO-A"/>);
 expect(screen.getByRole('checkbox')).toHaveProperty('checked',false);
});
it('shows an actionable persistent overlap notice without transport jargon',()=>{
 render(<ErrorNotice error={new ApiError(409,{code:'REGIMEN_OVERLAP',message:'DEMO conflict',rule_id:null})}/>);
 expect(screen.getByRole('alert').textContent).toContain('There is already a plan');
 expect(screen.getByRole('alert').textContent).not.toMatch(/HTTP|REGIMEN_OVERLAP/);
 fireEvent.click(screen.getByRole('button',{name:'Dismiss'}));expect(screen.queryByRole('alert')).toBeNull();
});
