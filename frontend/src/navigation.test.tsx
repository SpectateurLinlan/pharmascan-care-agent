// @vitest-environment jsdom
import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {useCareNavigation} from './navigation';
import {greetingAt,greetingName} from './greeting';

afterEach(()=>{cleanup();history.replaceState(null,'','/');});
function Navigation({blocked=false}:{blocked?:boolean}){const nav=useCareNavigation(blocked);return <><output>{nav.tab}</output>{['today','medicines','records','me','assistant','check','check-result','add-method','manual'].map(route=><button key={route} onClick={()=>nav.navigate(route)}>{route}</button>)}{!nav.isRoot?<button onClick={nav.back}>Back</button>:null}</>;}
it('twenty root selections replace their own entry and show no Back',()=>{
 render(<Navigation/>);const length=history.length;
 for(let i=0;i<20;i++)fireEvent.click(screen.getByText(['medicines','records','me','today'][i%4]!,{selector:'button'}));
 expect(history.length).toBe(length);expect(screen.queryByText('Back')).toBeNull();
});
it('returns assistant to its actual origin and deep links have explicit parent fallback',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('medicines',{selector:'button'}));fireEvent.click(screen.getByText('assistant',{selector:'button'}));fireEvent.click(screen.getByText('Back'));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
 cleanup();history.replaceState(null,'','#manual');render(<Navigation/>);fireEvent.click(screen.getByText('Back'));expect(screen.getByRole('status').textContent).toBe('add-method');
});
it('locked guide blocks application route actions',()=>{render(<Navigation blocked/>);fireEvent.click(screen.getByText('records',{selector:'button'}));expect(screen.getByRole('status').textContent).toBe('today');});
it('does not overwrite an unconsumed identity callback URL',()=>{history.replaceState(null,'','/?code=DEMO-synthetic-callback');render(<Navigation/>);expect(location.search).toBe('?code=DEMO-synthetic-callback');fireEvent.click(screen.getByText('me',{selector:'button'}));expect(location.hash).toBe('');});
it.each([[0,'Hello'],[4,'Hello'],[5,'Good morning'],[11,'Good morning'],[12,'Good afternoon'],[17,'Good afternoon'],[18,'Good evening'],[23,'Good evening']])('uses patient local hour %s', (hour,greeting)=>{expect(greetingAt(new Date(`2026-10-15T${String(hour).padStart(2,'0')}:00:00+08:00`),'Asia/Singapore')).toBe(greeting);});
it('separates registered names from anonymous sessions and private identifiers',()=>{expect(greetingName(false,'Sarah','Guest')).toBe('Guest');expect(greetingName(true,' Sarah ','Guest')).toBe('Sarah');expect(greetingName(true,'demo@example.invalid','Guest')).toBe('Guest');expect(greetingName(true,' ','Guest')).toBe('Guest');expect(greetingAt(new Date('2026-10-15T00:00:00Z'),'America/New_York')).toBe('Good evening');});

it('photo result Back returns to acquisition then to its actual origin',async()=>{
 render(<Navigation/>);fireEvent.click(screen.getByText('medicines',{selector:'button'}));fireEvent.click(screen.getByText('check',{selector:'button'}));fireEvent.click(screen.getByText('check-result',{selector:'button'}));
 fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('check'));
 fireEvent.click(screen.getByText('Back'));await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('medicines'));
});
