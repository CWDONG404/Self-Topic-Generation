import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { LoaderCircle } from 'lucide-react';
import { cn } from '../../lib/utils';

const buttonVariants = cva(
  'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold transition active:scale-[.98] disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-pine-600 text-white shadow-sm hover:bg-pine-700',
        secondary: 'border border-stone-200 bg-white text-ink shadow-sm hover:border-stone-300 hover:bg-stone-50',
        ghost: 'text-stone-600 hover:bg-stone-100 hover:text-ink',
        danger: 'bg-red-50 text-red-700 hover:bg-red-100',
        soft: 'bg-pine-50 text-pine-700 hover:bg-pine-100',
      },
      size: {
        sm: 'min-h-9 rounded-lg px-3 text-xs',
        md: 'min-h-10 px-4',
        lg: 'min-h-12 px-5 text-base',
        icon: 'h-10 min-h-10 w-10 px-0',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" /> : null}
      {children}
    </button>
  ),
);
Button.displayName = 'Button';

export { buttonVariants };
