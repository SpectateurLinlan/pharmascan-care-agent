// @vitest-environment jsdom
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {CaregiversScreen} from './CaregiversScreen';
import {api, type CaregiverContact} from '../api/client';
vi.mock('../api/client',()=>({ApiError:class extends Error{},api:{caregivers:vi.fn(),createCaregiver:vi.fn(),updateCaregiver:vi.fn(),deleteCaregiver:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const row:CaregiverContact={id:'00000000-0000-0000-0000-000000000321',patient_id:'DEMO-owner',name:'DEMO Caregiver',relationship:'DEMO relative',contact_type:'email',contact_value:'caregiver@example.invalid',storage_consent:true,verification_status:'pending',notifications_enabled:false,sharing_enabled:false,created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z',demo_only:true};

it('loads contacts, creates only after explicit storage consent and never claims verification or notification',async()=>{
  vi.mocked(api.caregivers).mockResolvedValue([]);vi.mocked(api.createCaregiver).mockResolvedValue(row);
  render(<CaregiversScreen newId={()=>row.id}/>);await screen.findByText('No caregiver contacts saved yet.');
  fireEvent.click(screen.getByRole('button',{name:'Add caregiver contact'}));
  fireEvent.change(screen.getByLabelText('Contact name'),{target:{value:row.name}});
  fireEvent.change(screen.getByLabelText('Relationship (optional)'),{target:{value:row.relationship}});
  fireEvent.change(screen.getByLabelText('Email address'),{target:{value:row.contact_value}});
  expect((screen.getByRole('button',{name:'Save contact'}) as HTMLButtonElement).disabled).toBe(true);
  expect(api.createCaregiver).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:'Save contact'}));await screen.findByRole('heading',{name:row.name});
  expect(api.createCaregiver).toHaveBeenCalledExactlyOnceWith({id:row.id,name:row.name,relationship:row.relationship,contact_type:'email',contact_value:row.contact_value,storage_consent:true});
  expect(screen.getByText(/Not verified.*Notifications off.*No record access/)).toBeTruthy();
  expect(screen.queryByText(row.patient_id)).toBeNull();
});

it('edits saved contact and requires an independent delete confirmation with safe cancellation',async()=>{
  vi.mocked(api.caregivers).mockResolvedValue([row]);vi.mocked(api.updateCaregiver).mockResolvedValue({...row,name:'DEMO Updated'});vi.mocked(api.deleteCaregiver).mockResolvedValue({deleted:true});
  render(<CaregiversScreen/>);await screen.findByRole('heading',{name:row.name});
  fireEvent.click(screen.getByRole('button',{name:'Edit contact'}));fireEvent.change(screen.getByLabelText('Contact name'),{target:{value:'DEMO Updated'}});
  fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Save contact'}));await screen.findByRole('heading',{name:'DEMO Updated'});
  expect(api.updateCaregiver).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole('button',{name:'Delete contact'}));expect(api.deleteCaregiver).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
  expect(api.deleteCaregiver).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Delete contact'}));fireEvent.click(screen.getByRole('button',{name:'Confirm deletion'}));
  await screen.findByText('No caregiver contacts saved yet.');expect(api.deleteCaregiver).toHaveBeenCalledExactlyOnceWith(row.id);
});

it('failed create keeps the same retry id and failed list does not pretend to be empty',async()=>{
  vi.mocked(api.caregivers).mockRejectedValueOnce(new Error('SIMULATED unavailable')).mockResolvedValue([]);
  vi.mocked(api.createCaregiver).mockRejectedValueOnce(new Error('SIMULATED unavailable')).mockResolvedValue(row);
  render(<CaregiversScreen newId={()=>row.id}/>);await screen.findByRole('button',{name:'Retry loading contacts'});
  expect(screen.queryByText('No caregiver contacts saved yet.')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Retry loading contacts'}));await screen.findByText('No caregiver contacts saved yet.');
  fireEvent.click(screen.getByRole('button',{name:'Add caregiver contact'}));fireEvent.change(screen.getByLabelText('Contact name'),{target:{value:row.name}});fireEvent.change(screen.getByLabelText('Email address'),{target:{value:row.contact_value}});fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:'Save contact'}));await waitFor(()=>expect(screen.getByRole('button',{name:'Save contact'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Save contact'}));await screen.findByRole('heading',{name:row.name});
  expect(api.createCaregiver).toHaveBeenCalledTimes(2);expect(vi.mocked(api.createCaregiver).mock.calls.map(call=>call[0].id)).toEqual([row.id,row.id]);
});
