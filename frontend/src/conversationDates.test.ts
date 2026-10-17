import {expect,it} from 'vitest';
import {conversationDateGroups,localDateKey} from './conversationDates';
const row=(id:string,stamp:string)=>({id,user_text:`DEMO ${id}`,assistant_text:'DEMO answer',created_at:stamp});
it('groups true saved exchanges by patient local date, not UTC date or inferred session',()=>{
 const groups=conversationDateGroups([row('a','2026-10-16T16:05:00Z'),row('b','2026-10-17T02:00:00Z'),row('c','2026-10-16T15:59:00Z'),row('d','2026-10-14T12:00:00Z')],'Asia/Singapore',new Date('2026-10-17T03:00:00Z'));
 expect(groups.map(group=>[group.date,group.relative,group.rows.length])).toEqual([['2026-10-17','Today',2],['2026-10-16','Yesterday',1],['2026-10-14',null,1]]);
 expect(groups[0]!.rows.map(value=>value.id)).toEqual(['a','b']);
});
it('handles yesterday across DST and year boundaries without subtracting 24 hours locally',()=>{
 expect(conversationDateGroups([row('a','2026-03-08T06:00:00Z')],'America/New_York',new Date('2026-03-09T04:15:00Z'))[0]!.relative).toBe('Yesterday');
 expect(conversationDateGroups([row('b','2025-12-31T10:00:00Z')],'Asia/Singapore',new Date('2025-12-31T16:01:00Z'))[0]!.relative).toBe('Yesterday');
 expect(localDateKey('not-a-date','Asia/Singapore')).toBe('unknown');
});
