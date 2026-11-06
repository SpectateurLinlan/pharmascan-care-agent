import { startApplication } from './app/bootstrap';

const root = document.getElementById('root');
if (!root) {
  throw new Error('root element is missing from index.html');
}

startApplication(root, () => import('./app/mountApplication'));
