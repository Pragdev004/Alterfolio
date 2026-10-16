import type { Register } from 'claude-code'
import type { RouterState, Tier, Usage } from '../types'

const TIERS: Record<Tier, { model: string; effort: 'low' | 'medium' }> = {
  opus: { model: 'claude-opus-5-5', effort: 'medium' },
  sonnet: { model: 'claude-sonnet-5-5', effort: 'medium' },
  haiku: { model: 'claude-haiku-5-5', effort: 'low' },
}
const OPUS_WORDS = /\b(spec|design|review|architecture)\b/i
const DEFAULT_BUDGET = 1_200_000
const LONG_PROMPT = 600
const REF = { plugin: 'model-router', key: 'router' } as const
const TOOL = 'mcp__model-router__route_model'

const fresh = (): RouterState => ({
  tier: 'sonnet', phase: 'init', isExplicit: false, switches: 0, applied: {}, agentTiers: {},
  byModel: {}, byPhase: {}, isWarned: false, isExhausted: false,
})
const zero = (): Usage => ({ input: 0, output: 0, cacheRead: 0, cacheCreation: 0 })
const add = (a: Usage | undefined, b: Usage): Usage => {
  const u = a ?? zero()
  return {
    input: u.input + b.input, output: u.output + b.output,
    cacheRead: u.cacheRead + b.cacheRead, cacheCreation: u.cacheCreation + b.cacheCreation,
  }
}
const sum = (m: Record<string, Usage>) =>
  Object.values(m).reduce((s, u) => ({ i: s.i + u.input, o: s.o + u.output }), { i: 0, o: 0 })

const load = async ($: any): Promise<RouterState> => {
  const { value } = await $.state.get(REF)
  return value ?? fresh()
}
const save = ($: any, s: RouterState) => $.state.set(REF, s)

const budget = async ($: any) => {
  const raw = Number(await $.env.get('TOKEN_BUDGET'))
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_BUDGET
}
const status = ($: any, s: RouterState, model?: string) => {
  const t = sum(s.byModel)
  $.ui.status(`router: ${model ?? TIERS[s.tier].model} | session in/out ${t.i}/${t.o} | switches ${s.switches}`)
}
const dateStr = async ($: any) => new Date(await $.clock.now()).toISOString().slice(0, 10)
const logLine = async ($: any, line: string) => {
  const top = await $.process.run({ argv: ['git', 'rev-parse', '--show-toplevel'] }).catch(() => undefined)
  const root = top && top.exitCode === 0 ? String(top.stdout).trim().split('\\').join('/') : ''
  const path = `${root ? root + '/' : ''}docs/reports/token-usage-${await dateStr($)}.md`
  const old = await $.fs.read(path).catch(() => '# Token usage (model-router)\n\n')
  await $.fs.write(path, `${old}${line}\n`)
}
const bump = async ($: any, model: string, u: Usage) => {
  const life = ((await $.store.get('lifetime')) ?? {}) as Record<string, Usage>
  await $.store.set('lifetime', { ...life, [model]: add(life[model], u) })
}

export const register: Register = (on) => {
  on('session.start', async ($, e, next) => {
    await $.tool.register({
      name: 'route_model',
      description:
        'Choose the model tier for the next work. tier: opus|sonnet|haiku. phase: short phase name. reason: why. ' +
        'Call at the start of every phase. Returns "BUDGET EXHAUSTED" when the token budget is spent.',
      inputSchema: {
        type: 'object',
        properties: {
          tier: { type: 'string', enum: ['opus', 'sonnet', 'haiku'] },
          phase: { type: 'string' },
          reason: { type: 'string' },
        },
        required: ['tier', 'phase', 'reason'],
      },
    })
    await $.command.register({ name: 'tokens', description: 'Per-model and per-phase token usage.' })
    return next(e)
  })

  on('tool.call', { tool: TOOL }, async ($, e: any) => {
    const s = await load($)
    const text = (t: string) => ({ result: t }) as any
    const tier = e.tier as Tier
    if (!(tier in TIERS)) return text(`Unknown tier "${String(e.tier)}"; use opus|sonnet|haiku.`)
    const t = sum(s.byModel)
    if (t.i + t.o >= (await budget($))) {
      await save($, { ...s, isExhausted: true })
      return text('BUDGET EXHAUSTED')
    }
    const next: RouterState = { ...s, isExplicit: true }
    if (e.agentId) next.agentTiers = { ...s.agentTiers, [e.agentId]: tier }
    else next.tier = tier
    const phase = String(e.phase ?? s.phase)
    if (!e.agentId && phase !== s.phase) {
      next.phase = phase
      const line = `- ${phase} | tier ${tier} | in/out ${t.i}/${t.o} | switches ${s.switches} | ${String(e.reason ?? '')}`
      await logLine($, line).catch(() => {})
    }
    await save($, next)
    status($, next)
    return text(`ok: ${tier} -> ${TIERS[tier].model} (effort ${TIERS[tier].effort}), phase ${phase}`)
  }).catch(($, e, next) => (next.called ? next(e) : { deny: 'model-router: route_model failed.' }))

  on('prompt.submit', async ($, e, next) => {
    const s = await load($)
    if (!s.isExplicit && e.text.length < LONG_PROMPT) {
      const tier: Tier = OPUS_WORDS.test(e.text) ? 'opus' : 'sonnet'
      if (tier !== s.tier) await save($, { ...s, tier })
    }
    return next(e)
  }).catch(($, e, next) => (next.called ? next(e) : next(e)))

  on('turn.step', async function* ($, e, next) {
    const s = await load($)
    const tier = (e.agentId && s.agentTiers[e.agentId]) || s.tier
    const { model, effort } = TIERS[tier]
    const key = e.agentId ?? 'main'
    const res = yield* next({ ...e, model, effort })
    const u = res.usage
    const prev = s.applied[key]
    const cur = await load($)
    const upd: RouterState = { ...cur, applied: { ...cur.applied, [key]: model } }
    if (prev !== undefined && prev !== model) upd.switches = cur.switches + 1
    if (u) {
      const d: Usage = {
        input: u.input_tokens, output: u.output_tokens,
        cacheRead: u.cache_read_input_tokens, cacheCreation: u.cache_creation_input_tokens,
      }
      upd.byModel = { ...cur.byModel, [u.model]: add(cur.byModel[u.model], d) }
      upd.byPhase = { ...cur.byPhase, [cur.phase]: add(cur.byPhase[cur.phase], d) }
      await bump($, u.model, d)
      const t = sum(upd.byModel)
      const b = await budget($)
      if (!cur.isWarned && t.i + t.o >= b * 0.8) {
        upd.isWarned = true
        $.ui.toast(`router: 80% of token budget used (${t.i + t.o}/${b})`)
      }
    }
    await save($, upd)
    status($, upd, model)
    return res
  })

  on('command.run', { command: 'tokens' }, async ($) => {
    const s = await load($)
    const life = ((await $.store.get('lifetime')) ?? {}) as Record<string, Usage>
    const row = (k: string, u: Usage) => `  ${k}: in ${u.input} out ${u.output} cache_read ${u.cacheRead} cache_write ${u.cacheCreation}`
    const lines = [
      `tier ${s.tier} | phase ${s.phase} | switches ${s.switches} | budget ${await budget($)}`,
      'per model (session):', ...Object.entries(s.byModel).map(([k, u]) => row(k, u)),
      'per phase (session):', ...Object.entries(s.byPhase).map(([k, u]) => row(k, u)),
      'per model (lifetime):', ...Object.entries(life).map(([k, u]) => row(k, u)),
    ]
    return { text: lines.join('\n') }
  })
}
