import type {ImageRoute} from './api/client';

/** Type evidence routes a task; it never verifies a medicine or authorizes a tool. */
export function sourceRoute(route:ImageRoute):'package'|'pharmacy_label'|'prescription'|'pill'|'clarify'{
 if(!route.checked||route.image_type==='unchecked')return 'clarify';
 // Upstream abstained means no loose-pill comparison; printed documents may
 // legitimately abstain from that comparison while still supporting OCR.
 if(route.image_type==='package')return 'package';
 if(route.image_type==='printed')return 'pharmacy_label';
 if(route.image_type==='document')return 'prescription';
 if(route.image_type==='loose_pills'&&!route.abstained)return 'pill';
 return 'clarify';
}
