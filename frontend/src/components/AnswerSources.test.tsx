// @vitest-environment jsdom
import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import type {ToolTrace} from '../api/client';
import {LanguageProvider} from '../language';
import {AnswerSources} from './AnswerSources';

afterEach(()=>{cleanup();localStorage.clear();});
const source={url:'https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=DEMO',label_name:'DEMO source oral solution',version:'2',effective_time:'20260101',sections:[{field:'indications_and_usage',text:'DEMO original indication limited to adults.'}]};
function trace(sources:unknown[]):ToolTrace{return {tool_name:'get_long_term_care',status:'success',error_code:null,requires_confirmation:false,clarification_question:null,payload:{general_knowledge:{status:'matched',sources}}};}

it('deduplicates shared evidence, retains source brand and scope, and starts collapsed',()=>{
 render(<LanguageProvider><AnswerSources traces={[trace([source]),trace([source])]}/></LanguageProvider>);
 const summary=screen.getByText('Knowledge sources');const details=summary.closest('details')!;
 expect(details.open).toBe(false);fireEvent.click(summary);expect(details.open).toBe(true);
 expect(screen.getAllByRole('link')).toHaveLength(1);
 expect(screen.getByRole('link').textContent).toContain('DEMO source oral solution');
 expect(screen.getByRole('link').getAttribute('href')).toBe(source.url);
 expect(screen.getByText(/Their brands, forms and release types/)).toBeTruthy();
 const original=screen.getByText('Original use excerpt (source label scope)');fireEvent.click(original);
 expect(original.closest('details')!.open).toBe(true);
 expect(screen.getByText(source.sections[0]!.text)).toBeTruthy();
});

it('rejects unsafe source URLs and renders source text as text rather than HTML',()=>{
 render(<LanguageProvider><AnswerSources traces={[trace([{...source,url:'javascript:alert(1)'},{...source,url:'https://evil.example/label'},{...source,label_name:'<script>DEMO</script>'}])]}/></LanguageProvider>);
 fireEvent.click(screen.getByText('Knowledge sources'));
 expect(screen.getAllByRole('link')).toHaveLength(1);
 expect(screen.getByRole('link').textContent).toContain('<script>DEMO</script>');
 expect(document.querySelector('script')).toBeNull();
});
