export function selectedCandidates(operation, choice) {
  return operation.instruction.operation === 'delete' && choice.candidates
    ? choice.candidates : choice.candidate === null ? [] : [choice.candidate]
}

export function needsScope(operation, choice) {
  return operation.instruction.operation !== 'create' && selectedCandidates(operation, choice)
    .some(index => operation.candidates[index]?.recurrence || operation.candidates[index]?.series_parent_id)
}

export function commandReady(command, choices) {
  return !!command && choices.some(choice => !choice.skip) && choices.every((choice, index) => {
    if (choice.skip) return true
    const operation = command.operations[index]
    const selected = selectedCandidates(operation, choice)
    return selected.length > 0 && selected.every(n => Number.isInteger(n) && operation.candidates[n]) &&
      (!needsScope(operation, choice) || !!choice.scope)
  })
}

export function initialChoice(operation, scope = null) {
  return {candidate: operation.candidates.length === 1 ? 0 : null,
    ...(operation.instruction.operation === 'delete' ? {candidates: operation.candidates.length === 1 ? [0] : []} : {}), scope}
}
