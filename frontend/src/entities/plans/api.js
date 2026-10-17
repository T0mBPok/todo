import { request } from '../../shared/api'
export const createPlan = data => request('/plans', 'POST', data)
export const confirmPlan = (id, tasks) => request(`/plans/${id}/confirm`, 'POST', { tasks })
