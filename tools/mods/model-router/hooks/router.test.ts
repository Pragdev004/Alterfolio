import { test, expect, mock } from 'claude-code/testing'

const usage = (model: string, input: number, output: number) => ({
  model, input_tokens: input, output_tokens: output, cache_read_input_tokens: 5, cache_creation_input_tokens: 2,
})
const stepIn = { turnId: 't', index: 0, model: 'claude-sonnet-5-5', messageCount: 1 } as const

async function run($: any) {
  const s = $.turn.step(stepIn)
  for await (const _ of s) { /* drain */ }
  return s.result
}

function stubs(on: any, seen: string[], u: ReturnType<typeof usage>) {
  on('turn.step', async function* (_$: any, e: any) {
    seen.push(`${e.model}/${e.effort}`)
    return { turnId: 't', index: 0, answer: '', toolUses: [], stopReason: 'end_turn', usage: u }
  })
  on('fs.read', async () => { throw new Error('missing') })
  on('fs.write', async () => ({ value: undefined }))
  on('ui.status', async () => ({ value: undefined }))
  on('ui.toast', async () => ({ value: undefined }))
}

test('route_model switches the step model and counts one switch', async ($: any, on: any) => {
  mock.env(on, { TOKEN_BUDGET: '1000000' })
  mock.store(on)
  mock.clock(on)
  const seen: string[] = []
  stubs(on, seen, usage('claude-sonnet-5-5', 10, 20))
  const r = await $.tool.call({ tool: 'mcp__model-router__route_model', tier: 'opus', phase: 'review', reason: 'x' })
  expect(String(r.text ?? JSON.stringify(r.result))).toContain('claude-opus-5-5')
  await run($)
  await $.tool.call({ tool: 'mcp__model-router__route_model', tier: 'sonnet', phase: 'tests', reason: 'x' })
  await run($)
  await run($)
  expect(seen).toEqual(['claude-opus-5-5/medium', 'claude-sonnet-5-5/medium', 'claude-sonnet-5-5/medium'])
  const out = await $.command.run({ command: 'tokens', args: '', origin: 'composer' })
  expect(out.text).toContain('switches 1')
  expect(out.text).toContain('claude-sonnet-5-5: in 30 out 60')
})

test('budget guard returns BUDGET EXHAUSTED at 100%', async ($: any, on: any) => {
  mock.env(on, { TOKEN_BUDGET: '50' })
  mock.store(on)
  mock.clock(on)
  stubs(on, [], usage('claude-sonnet-5-5', 30, 30))
  await run($)
  const r = await $.tool.call({ tool: 'mcp__model-router__route_model', tier: 'sonnet', phase: 'p', reason: 'x' })
  expect(String(r.text ?? JSON.stringify(r.result))).toContain('BUDGET EXHAUSTED')
})
