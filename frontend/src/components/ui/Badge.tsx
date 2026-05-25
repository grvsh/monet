import { cn } from '../../lib/utils'
import type { ReactNode } from 'react'

type BadgeVariant = 'default' | 'blue' | 'green' | 'yellow' | 'red' | 'neutral'

interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
  className?: string
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-neutral-700 text-neutral-300',
  blue: 'bg-blue-900/70 text-blue-300',
  green: 'bg-green-900/70 text-green-300',
  yellow: 'bg-yellow-900/70 text-yellow-300',
  red: 'bg-red-900/70 text-red-300',
  neutral: 'bg-neutral-800 text-neutral-400',
}

export function Badge({ children, variant = 'default', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium',
        variantClasses[variant],
        className
      )}
    >
      {children}
    </span>
  )
}
