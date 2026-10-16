export function greetingAt(now:Date,timezone:string):string {
  const hour=Number(new Intl.DateTimeFormat('en',{hour:'numeric',hourCycle:'h23',timeZone:timezone}).format(now));
  return hour>=5&&hour<12?'Good morning':hour>=12&&hour<18?'Good afternoon':hour>=18?'Good evening':'Hello';
}
export function greetingName(member:boolean,name:string|null|undefined,guest:string):string {
  const clean=name?.trim();return member&&clean&&!clean.includes('@')&&!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(clean)?clean:guest;
}
