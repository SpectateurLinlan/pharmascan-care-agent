/** Wire notification device actions to the existing authorized backend facade. */
import { api } from '../../api/client';
import { createWebPushActions } from '../../platform/notifications/webPush';

export { pushSupported } from '../../platform/notifications/webPush';
export type { WebPushActionOptions } from '../../platform/notifications/webPush';
export const { enableWebPush, currentWebPush, disableWebPush } = createWebPushActions(api);
