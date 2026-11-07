export const categories = [
 {value:'important_urgent',label:'Важное и срочное',hint:'Сделать в первую очередь'},
 {value:'important_not_urgent',label:'Важное, не срочное',hint:'Запланировать время'},
 {value:'not_important_urgent',label:'Неважное, но срочное',hint:'Сделать быстро или делегировать'},
 {value:'not_important_not_urgent',label:'Неважное и не срочное',hint:'Отложить или отказаться'}
]
export const categoryLabel = value => categories.find(c=>c.value===value)?.label || 'Важное, не срочное'
