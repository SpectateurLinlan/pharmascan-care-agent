// @vitest-environment jsdom
import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {useCareNavigation} from './navigation';
import {greetingAt,greetingName} from './greeting';

afterEach(()=>{cleanup();history.replaceState(null,'','/');});
function Navigation({blocked=false}:{blocked?:boolean}){const nav=useCareNavigation(blocked);return <><output>{nav.tab}</output>{['today','medicines','records','medication-records','me','assistant','check','check-result','label','manual','medicine-detail','medicine-history'].map(route=><button key={route} onClick={()=>nav.navigate(route)}>{route}</button>)}<button onClick={()=>nav.navigate('medicines',undefined,{preserveOrigin:true})}>Today medicines link</button><button onClick={()=>nav.navigate('records',undefined,{preserveOrigin:true})}>Today records link</button><button onClick={()=>nav.navigate('medicines',undefined,{replace:true})}>Guide route</button><button onClick={()=>nav.restore('today',{search:'kept'},['today'])}>Restore guide origin</button>{!nav.isRoot?<button onClick={nav.back}>Back</button>:null}</>;}
it('twenty root selections replace their own entry and show no Back',()=>{
 render(<Navigation/>);const length=history.length;
 for(let i=0;i<20;i++)fireEvent.click(screen.getByText(['medicines','records','me','today'][i%4]!,{selector:'button'}));
 expect(history.length).toBe(length);expect(screen.queryByText('Back')).toBeNull();
});
it('returns assistant to its actual origin and deep links have explicit parent fallback',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('medicines',{selector:'button'}));fireEvent.click(screen.getByText('assistant',{selector:'button'}));fireEvent.click(screen.getByText('Back'));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 cleanup();history.replaceState(null,'','#manual');render(<Navigation/>);fireEvent.click(screen.getByText('Back'));expect(screen.getByRole('status').textContent).toBe('medicines');
});
it('locked guide blocks application route actions',()=>{render(<Navigation blocked/>);fireEvent.click(screen.getByText('records',{selector:'button'}));expect(screen.getByRole('status').textContent).toBe('today');});
it('does not overwrite an unconsumed identity callback URL',()=>{history.replaceState(null,'','/?code=DEMO-synthetic-callback');render(<Navigation/>);expect(location.search).toBe('?code=DEMO-synthetic-callback');fireEvent.click(screen.getByText('me',{selector:'button'}));expect(location.hash).toBe('');});
it('preserves a direct route query through navigation initialization and guide restoration',async()=>{
 history.replaceState({careRoute:['today']},'','#today?search=amlodipine&range=30');render(<Navigation/>);
 await waitFor(()=>expect(location.hash).toBe('#today?search=amlodipine&range=30'));
 fireEvent.click(screen.getByText('Guide route'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 fireEvent.click(screen.getByText('Restore guide origin'));expect(location.hash).toBe('#today?search=kept');
});
it('preserves medication, photo, and gallery state when navigation initializes a direct gallery URL',async()=>{
 const href='#gallery?medication_id=DEMO-med&photo_id=DEMO-photo&search=metformin&sort=updated';history.replaceState(null,'',href);render(<Navigation/>);
 await waitFor(()=>expect(location.hash).toBe(href));expect(screen.getByRole('status').textContent).toBe('gallery');
});
it.each([[0,'Hello'],[4,'Hello'],[5,'Good morning'],[11,'Good morning'],[12,'Good afternoon'],[17,'Good afternoon'],[18,'Good evening'],[23,'Good evening']])('uses patient local hour %s', (hour,greeting)=>{expect(greetingAt(new Date(`2026-10-15T${String(hour).padStart(2,'0')}:00:00+08:00`),'Asia/Singapore')).toBe(greeting);});
it('separates registered names from anonymous sessions and private identifiers',()=>{expect(greetingName(false,'Sarah','Guest')).toBe('Guest');expect(greetingName(true,' Sarah ','Guest')).toBe('Sarah');expect(greetingName(true,'demo@example.invalid','Guest')).toBe('Guest');expect(greetingName(true,' ','Guest')).toBe('Guest');expect(greetingAt(new Date('2026-10-15T00:00:00Z'),'America/New_York')).toBe('Good evening');});

it('photo result Back returns to acquisition then to its actual origin',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('medicines',{selector:'button'}));fireEvent.click(screen.getByText('check',{selector:'button'}));fireEvent.click(screen.getByText('check-result',{selector:'button'}));
 fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('check'));
 fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
});
it('returns medication-scoped history to its exact detail route',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('medicines',{selector:'button'}));fireEvent.click(screen.getByText('medicine-detail',{selector:'button'}));fireEvent.click(screen.getByText('medicine-history',{selector:'button'}));
 expect(screen.getByRole('status').textContent).toBe('medicine-history');fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicine-detail'));
});
it('preserves Today as contextual origin through Medicines and Detail for in-app and browser Back/Forward',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('Today medicines link'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 fireEvent.click(screen.getByText('medicine-detail',{selector:'button'}));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicine-detail'));
 fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('today'));
 history.forward();await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 history.forward();await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicine-detail'));
 history.back();await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
});
it('makes contextual Records navigation return to Today without changing main-tab root behavior',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('Today records link'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('records'));
 expect(screen.getByText('Back')).toBeTruthy();fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('today'));
 fireEvent.click(screen.getByText('records',{selector:'button'}));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('records'));expect(screen.queryByText('Back')).toBeNull();
});
it('replaces history during guided routes and restores the origin query in place',async()=>{
 history.replaceState({careRoute:['today']},'','#today?search=original');render(<Navigation/>);const length=history.length;
 fireEvent.click(screen.getByText('Guide route'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 fireEvent.click(screen.getByText('records',{selector:'button'}));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('records'));
 expect(history.length).toBe(length);fireEvent.click(screen.getByText('Restore guide origin'));
 expect(location.hash).toBe('#today?search=kept');expect(history.length).toBe(length);
});
it('returns the medication records child page to Records using the existing navigation stack',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('records',{selector:'button'}));fireEvent.click(screen.getByText('medication-records',{selector:'button'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medication-records'));fireEvent.click(screen.getByText('Back'));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('records'));
});
it('uses Records as the fallback for a direct medication-records URL',()=>{
 history.replaceState(null,'','#medication-records');render(<Navigation/>);expect(screen.getByRole('status').textContent).toBe('medication-records');
 fireEvent.click(screen.getByText('Back'));expect(screen.getByRole('status').textContent).toBe('records');
});
it('uses a sensible Medicines fallback for direct Detail links and retains a saved route stack on refresh',async()=>{
 history.replaceState(null,'','#medicine-detail');render(<Navigation/>);expect(screen.getByRole('status').textContent).toBe('medicine-detail');
 fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 cleanup();history.replaceState(null,'','#today');render(<Navigation/>);fireEvent.click(screen.getByText('Today medicines link'));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));const savedState=history.state;
 cleanup();history.replaceState(savedState,'','#medicines');render(<Navigation/>);
 expect(screen.getByRole('status').textContent).toBe('medicines');fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('today'));
});
