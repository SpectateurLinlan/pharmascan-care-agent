import type {HealthObservation} from './api/client';

/** Preserve the saved measurement and unit in both screen and exported reports. */
export function observationText(row:HealthObservation):string{
 const measurement=row.value==null?'':`${row.value}${row.secondary_value==null?'':`/${row.secondary_value}`} ${row.unit??''}`.trim();
 return [row.description,measurement,row.notes].filter(Boolean).join(' · ');
}
