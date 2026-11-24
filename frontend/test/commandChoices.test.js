import { test } from 'node:test'
import assert from 'node:assert/strict'
import { commandReady, initialChoice, needsScope, executionChoices } from '../src/shared/commandChoices.js'

const operation = {instruction: {operation: 'delete'}, candidates: [{recurrence: {}}, {recurrence: {}}]}
test('both recurring candidates can be selected with a future boundary', () => {
  const choice = initialChoice(operation)
  assert.equal(commandReady({operations: [operation]}, [choice]), false)
  choice.candidates = [0, 1]
  assert.equal(needsScope(operation, choice), true)
  assert.equal(commandReady({operations: [operation]}, [choice]), false)
  choice.scope = 'future'
  assert.equal(commandReady({operations: [operation]}, [choice]), true)
  choice.candidates = []
  assert.equal(commandReady({operations: [operation]}, [choice]), false)
})

test('single selection for changes and additions stays compatible', () => {
  const update = {...operation, instruction: {operation: 'update'}}
  const choice = initialChoice(update)
  choice.candidate = 1
  choice.scope = 'series'
  assert.equal(commandReady({operations: [update]}, [choice]), true)
  const create = {instruction: {operation: 'create'}, candidates: [{}]}
  assert.equal(commandReady({operations: [create]}, [initialChoice(create)]), true)
})

test('browser payload omits the empty single choice when multiple events are selected', () => {
  const choice = initialChoice(operation)
  choice.candidates = [0, 1]
  choice.scope = 'future'
  assert.equal(choice.candidate, null)
  const payload = executionChoices({operations: [operation]}, [choice])
  assert.deepEqual(payload, [{candidates: [0, 1], scope: 'future'}])
  assert.equal(choice.candidate, null)
})
