export type Tier = 'opus' | 'sonnet' | 'haiku'
export type Usage = { input: number; output: number; cacheRead: number; cacheCreation: number }
export type RouterState = {
  tier: Tier
  phase: string
  isExplicit: boolean
  switches: number
  applied: Record<string, string>
  agentTiers: Record<string, Tier>
  byModel: Record<string, Usage>
  byPhase: Record<string, Usage>
  isWarned: boolean
  isExhausted: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'model-router': { router: RouterState }
  }
}
