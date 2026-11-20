import { test } from 'node:test'
import assert from 'node:assert/strict'
import { request, readApiResponse } from '../src/shared/api.js'
import { AppError, errorMessage, publicMessage, installErrorHandlers } from '../src/shared/errors.js'

test('API failures never display a request id while preserving a useful business message', async () => {
  const id='a'.repeat(32)
  const response=new Response(JSON.stringify({detail:'Не удалось отправить письмо. Код запроса: '+id}),{status:502,headers:{'X-Request-ID':id}})
  await assert.rejects(readApiResponse(response),error=>{
    assert.equal(error.status,502)
    assert.equal(error.message,'Не удалось отправить письмо.')
    assert.equal(error.detail,error.message)
    assert.ok(!error.message.includes(id))
    return true
  })
})
test('HTML proxy errors, structured validation and technical diagnostics become readable messages',async()=>{
  for(const [response,expected] of [
    [new Response('<html>Bad gateway private upstream</html>',{status:502}),/Сервис временно/],
    [new Response(JSON.stringify({detail:[{input:'private value',msg:'invalid'}]}),{status:422}),/Проверьте/],
    [new Response(JSON.stringify({detail:'Ошибка sqlalchemy SELECT private FROM users'}),{status:500}),/ошибки сервиса/]
  ]) await assert.rejects(readApiResponse(response),error=>{assert.match(error.message,expected);assert.doesNotMatch(error.message,/private|sqlalchemy|<html>/);return true})
})
test('network and invalid JSON responses have custom messages',async()=>{
  const original=globalThis.fetch
  try {
    globalThis.fetch=async()=>{throw new TypeError('Failed to fetch private host')}
    await assert.rejects(request('/tasks'),error=>error instanceof AppError && /Проверьте интернет/.test(error.message))
  } finally {globalThis.fetch=original}
  await assert.rejects(readApiResponse(new Response('broken json',{status:200})),/Не удалось прочитать/)
  assert.equal(await readApiResponse(new Response(null,{status:204})),null)
})
test('unknown JavaScript errors and leaked diagnostic fragments are hidden',()=>{
  assert.doesNotMatch(errorMessage(new Error('Cannot read private token property')),/private|Cannot/)
  assert.equal(publicMessage('Уточните время. request_id=secret-id',422),'Уточните время.')
})
test('Vue and unhandled promise errors use the same dismissible notice channel',()=>{
  const listeners={},messages=[],app={config:{}}
  const target={addEventListener:(name,fn)=>listeners[name]=fn,dispatchEvent:event=>messages.push(event.detail)}
  installErrorHandlers(app,target)
  app.config.errorHandler(new Error('Cannot read property at private.js'))
  let prevented=false
  listeners.unhandledrejection({reason:new Error('Ошибка. Код запроса: '+ 'b'.repeat(32)),preventDefault(){prevented=true}})
  assert.equal(messages.length,2)
  assert.ok(messages.every(value=>!value.includes('private')&&!value.includes('bbbb')))
  assert.equal(prevented,true)
})
