import {Component,Suspense,lazy,useState,type ComponentType,type ReactNode} from 'react';
import {useLanguage} from '../language';

function SectionStatus({retry}:{retry?:()=>void}){
 const {language}=useLanguage();
 return retry?<section><p role="alert">{language==='zh'?'这部分页面暂时无法加载。':'This section could not be loaded.'}</p><button onClick={retry}>{language==='zh'?'重试加载页面':'Retry loading section'}</button></section>
  :<p role="status">{language==='zh'?'正在加载这部分页面…':'Loading this section…'}</p>;
}

class SectionBoundary extends Component<{children:ReactNode;retry:()=>void},{failed:boolean}>{
 state={failed:false};
 static getDerivedStateFromError(){return {failed:true};}
 render(){return this.state.failed?<SectionStatus retry={this.props.retry}/>:this.props.children;}
}

/** Each section owns its loading/error boundary; the surrounding shell stays mounted. */
export function deferScreen<P extends object>(load:()=>Promise<{default:ComponentType<P>}>):ComponentType<P>{
 return function DeferredScreen(props:P){
  const [Content,setContent]=useState(()=>lazy(load));
  const [attempt,setAttempt]=useState(0);
  // React's lazy type adds a generic ref union; the loaded screen retains P.
  const View=Content as unknown as ComponentType<P>;
  function retry(){setContent(()=>lazy(load));setAttempt(value=>value+1);}
  return <SectionBoundary key={attempt} retry={retry}><Suspense fallback={<SectionStatus/>}><View {...props}/></Suspense></SectionBoundary>;
 };
}
