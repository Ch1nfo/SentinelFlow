const productName = (import.meta.env.VITE_PRODUCT_NAME as string | undefined)?.trim() || 'SentinelFlow'
const consoleTitle = (import.meta.env.VITE_CONSOLE_TITLE as string | undefined)?.trim() || `${productName} 控制台`
const platformTagline =
  (import.meta.env.VITE_PLATFORM_TAGLINE as string | undefined)?.trim() || 'AI Native SecOps Platform'
const workflowEngineLabel =
  (import.meta.env.VITE_WORKFLOW_ENGINE_LABEL as string | undefined)?.trim() || 'SentinelFlow Agent Workflow'

export const brand = {
  productName,
  consoleTitle,
  platformTagline,
  workflowEngineLabel,
}

export function withProductName(text: string): string {
  return text.split('SentinelFlow').join(brand.productName)
}
