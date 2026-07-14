import { useRef, useState } from 'react';
export function SpecInput({onSubmit, busy}:{onSubmit:(spec:string)=>void;busy:boolean}) {
 const [value,setValue]=useState(''); const file=useRef<HTMLInputElement>(null);
 const upload=(e:React.ChangeEvent<HTMLInputElement>)=>{const f=e.target.files?.[0]; const r=new FileReader(); if(f){r.onload=()=>setValue(String(r.result));r.readAsText(f)}};
 return <section className="input-panel"><p className="eyebrow">01 / INPUT</p><h1>Spec<br/><em>Adversary</em></h1><p className="intro">Send your product thesis into a room full of hostile specialists.</p><textarea value={value} onChange={e=>setValue(e.target.value)} placeholder="Paste a product or technical spec…"/><div className="input-actions"><button onClick={()=>file.current?.click()} className="secondary">Attach .md / .txt</button><input ref={file} type="file" accept=".md,.txt,text/plain" onChange={upload} hidden/><button disabled={busy||!value.trim()} onClick={()=>onSubmit(value)}>{busy?'RUNNING…':'RUN CRITICS →'}</button></div></section>
}
