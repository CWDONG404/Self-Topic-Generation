import * as RadixSelect from '@radix-ui/react-select';
import {
  Children,
  forwardRef,
  isValidElement,
  type ChangeEvent,
  type ReactNode,
} from 'react';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '../../lib/utils';

const EMPTY_VALUE = '__studyforge_empty_value__';

interface SelectOption {
  value: string;
  label: ReactNode;
  disabled: boolean;
}

function readOptions(children: ReactNode): SelectOption[] {
  const options: SelectOption[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement<{ value?: string | number; disabled?: boolean; children?: ReactNode }>(child)) return;
    if (child.type === 'option') {
      const rawValue = child.props.value == null ? String(child.props.children ?? '') : String(child.props.value);
      options.push({
        value: rawValue === '' ? EMPTY_VALUE : rawValue,
        label: child.props.children,
        disabled: Boolean(child.props.disabled),
      });
      return;
    }
    if (child.props.children) options.push(...readOptions(child.props.children));
  });
  return options;
}

export interface SelectProps {
  value?: string | number;
  defaultValue?: string | number;
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
  children: ReactNode;
  className?: string;
  containerClassName?: string;
  selectSize?: 'sm' | 'md';
  disabled?: boolean;
  required?: boolean;
  name?: string;
  id?: string;
  title?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  'aria-describedby'?: string;
  'aria-invalid'?: boolean | 'true' | 'false';
}

export const Select = forwardRef<HTMLButtonElement, SelectProps>(
  ({
    value,
    defaultValue,
    onChange,
    className,
    containerClassName,
    children,
    disabled,
    required,
    name,
    id,
    title,
    selectSize = 'md',
    ...ariaProps
  }, ref) => {
    const options = readOptions(children);
    const normalizeValue = (raw: string | number | undefined) => {
      if (raw == null) return undefined;
      return String(raw) === '' ? EMPTY_VALUE : String(raw);
    };
    const currentValue = normalizeValue(value);
    const initialValue = normalizeValue(defaultValue);

    const handleValueChange = (nextValue: string) => {
      const translated = nextValue === EMPTY_VALUE ? '' : nextValue;
      const target = { value: translated, name: name ?? '' } as HTMLSelectElement;
      onChange?.({ target, currentTarget: target } as ChangeEvent<HTMLSelectElement>);
    };

    return (
      <span className={cn('relative block min-w-0', containerClassName)}>
        <RadixSelect.Root
          value={currentValue}
          defaultValue={initialValue}
          onValueChange={handleValueChange}
          disabled={disabled}
          required={required}
          name={name}
        >
          <RadixSelect.Trigger
            ref={ref}
            id={id}
            title={title}
            className={cn(
              'group flex w-full items-center justify-between gap-3 border border-stone-200 bg-white text-left text-ink shadow-sm transition',
              'hover:border-pine-300 hover:bg-pine-50/30 focus:border-pine-500 focus:outline-none focus:ring-2 focus:ring-pine-500/15',
              'data-[state=open]:border-pine-500 data-[state=open]:ring-2 data-[state=open]:ring-pine-500/15',
              'disabled:cursor-not-allowed disabled:border-stone-200 disabled:bg-stone-100 disabled:text-stone-400 disabled:shadow-none',
              'aria-[invalid=true]:border-red-400 aria-[invalid=true]:focus:border-red-500 aria-[invalid=true]:focus:ring-red-500/15',
              selectSize === 'sm'
                ? 'min-h-10 rounded-lg px-3 py-2 text-xs font-semibold'
                : 'min-h-11 rounded-xl px-3.5 py-2.5 text-sm',
              className,
            )}
            {...ariaProps}
          >
            <RadixSelect.Value />
            <RadixSelect.Icon asChild>
              <ChevronDown
                aria-hidden="true"
                className="h-4 w-4 shrink-0 text-stone-400 transition group-data-[state=open]:rotate-180 group-data-[state=open]:text-pine-600"
              />
            </RadixSelect.Icon>
          </RadixSelect.Trigger>

          <RadixSelect.Portal>
            <RadixSelect.Content
              position="popper"
              sideOffset={6}
              collisionPadding={12}
              className="z-[80] max-h-[min(22rem,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border border-stone-200 bg-white p-1.5 shadow-xl data-[state=closed]:animate-fade-out data-[state=open]:animate-fade-in"
            >
              <RadixSelect.ScrollUpButton className="flex h-7 items-center justify-center text-stone-400">
                <ChevronUp aria-hidden="true" className="h-4 w-4" />
              </RadixSelect.ScrollUpButton>
              <RadixSelect.Viewport>
                {options.map((option) => (
                  <RadixSelect.Item
                    key={option.value}
                    value={option.value}
                    disabled={option.disabled}
                    className={cn(
                      'relative flex min-h-10 cursor-pointer select-none items-center rounded-lg py-2 pl-9 pr-3 text-sm text-stone-600 outline-none transition',
                      'data-[highlighted]:bg-pine-50 data-[highlighted]:text-pine-800 data-[state=checked]:font-semibold data-[state=checked]:text-pine-800',
                      'data-[disabled]:pointer-events-none data-[disabled]:text-stone-300',
                    )}
                  >
                    <RadixSelect.ItemIndicator className="absolute left-3 inline-flex items-center">
                      <Check aria-hidden="true" className="h-4 w-4 text-pine-600" />
                    </RadixSelect.ItemIndicator>
                    <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                  </RadixSelect.Item>
                ))}
              </RadixSelect.Viewport>
              <RadixSelect.ScrollDownButton className="flex h-7 items-center justify-center text-stone-400">
                <ChevronDown aria-hidden="true" className="h-4 w-4" />
              </RadixSelect.ScrollDownButton>
            </RadixSelect.Content>
          </RadixSelect.Portal>
        </RadixSelect.Root>
      </span>
    );
  },
);

Select.displayName = 'Select';
