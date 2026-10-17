import { request } from '../../shared/api'
export const listTasks = range => request('/tasks'+(range?'?'+new URLSearchParams(range):''))
export const createTask = data => request('/tasks', 'POST', data)
export const updateTask = (id, data, options) => request(`/tasks/${id}`+(options?"?"+new URLSearchParams(options):""), 'PUT', data)
export const deleteTask = (id,options) => request(`/tasks/${id}`+(options?'?'+new URLSearchParams(options):''), 'DELETE')
