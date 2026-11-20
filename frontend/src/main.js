import { createApp } from 'vue'
import App from './App.vue'
import { installErrorHandlers } from './shared/errors.js'
import './style.css'
import './impulse.css'
import './design.css'
const app = createApp(App)
installErrorHandlers(app)
app.mount('#app')
