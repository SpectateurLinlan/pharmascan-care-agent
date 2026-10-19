import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import './styles.css';

if(import.meta.env.DEV&&['http://localhost:5173','http://127.0.0.1:5173'].includes(window.location.origin)){
 void import('./api/localDiagnostics').then(({installLocalDiagnostics})=>{
  const dispose=installLocalDiagnostics(window);
  import.meta.hot?.dispose(dispose);
 });
}

const root = document.getElementById('root');
if (!root) {
  throw new Error('root element is missing from index.html');
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
