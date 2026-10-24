import { api } from './client'
import type { AuditFilters, AuditPage } from '../types/activity'

/** Replace this adapter when the backend audit contract is agreed; never synthesize real history. */
export const activitySource = {
  list: (filters: AuditFilters): Promise<AuditPage> => api.listAuditEvents(filters),
}
