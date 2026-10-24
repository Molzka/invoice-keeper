import { api } from './client'
import type { AuditFilters, AuditPage } from '../types/activity'

/** Real mode always reads the persistent server journal. */
export const activitySource = {
  list: (filters: AuditFilters): Promise<AuditPage> => api.listAuditEvents(filters),
}
