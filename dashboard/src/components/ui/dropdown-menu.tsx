import * as React from "react"
import { Menu } from "@headlessui/react"
import { Check, ChevronRight, Circle } from "lucide-react"

import { cn } from "@/lib/utils"

const DropdownMenu = Menu

const DropdownMenuTrigger = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <Menu.Button as={React.Fragment}>
    {typeof children === 'string'
      ? <span className={className}>{children}</span>
      : children}
  </Menu.Button>
)

const DropdownMenuGroup = ({ children }: { children: React.ReactNode }) => (
  <Menu.Items as={React.Fragment}>{children}</Menu.Items>
)

const DropdownMenuPortal = ({ children }: { children: React.ReactNode }) => <>{children}</>

const DropdownMenuSub = ({
  children,
}: {
  children: React.ReactNode
}) => <>{children}</> // Submenus not supported in Headless UI v2

const DropdownMenuRadioGroup = ({
  children,
}: {
  children: React.ReactNode
}) => <Menu.Items as={React.Fragment}>{children}</Menu.Items>

const DropdownMenuSubTrigger = ({
  inset,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { inset?: boolean }) => (
  <Menu.Item as="div">
    {({ active }: { active: boolean }) => (
      <div
        className={cn(
          "flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none",
          active ? "bg-accent text-accent-foreground" : "",
          inset ? "pl-8" : "",
          className
        )}
        {...props}
      >
        {children}
        <ChevronRight className="ml-auto h-4 w-4" />
      </div>
    )}
  </Menu.Item>
)

const DropdownMenuSubContent = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <Menu.Item as="div">
    {({ active }: { active: boolean }) => (
      <div
        className={cn(
          "z-50 min-w-[8rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-lg",
          active ? "bg-accent text-accent-foreground" : "",
          className
        )}
        {...props}
      />
    )}
  </Menu.Item>
)

const DropdownMenuContent = ({
  align,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { align?: 'start' | 'center' | 'end' }) => (
  <Menu.Items
    as="div"
    className={cn(
      "z-50 min-w-[8rem] overflow-y-auto overflow-x-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-lg data-[active]:bg-accent",
      align === 'end' ? "origin-top-right [&>*]:justify-end" : "",
      className
    )}
    {...props}
  />
)

const DropdownMenuItem = ({
  inset,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { inset?: boolean }) => (
  <Menu.Item>
    {({ active }: { active: boolean }) => (
      <div
        className={cn(
          "relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none transition-colors",
          active ? "bg-accent text-accent-foreground" : "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
          inset ? "pl-8" : "",
          className
        )}
        {...props}
      >
        {children}
      </div>
    )}
  </Menu.Item>
)

const DropdownMenuCheckboxItem = ({
  className,
  children,
  checked,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  checked?: boolean
}) => (
  <Menu.Item>
    {({ active }: { active: boolean }) => (
      <div
        className={cn(
          "relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors",
          active ? "bg-accent text-accent-foreground" : "",
          className
        )}
        role="checkbox"
        aria-checked={checked}
        {...props}
      >
        <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
          {checked && <Check className="h-4 w-4" />}
        </span>
        {children}
      </div>
    )}
  </Menu.Item>
)

const DropdownMenuRadioItem = ({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <Menu.Item>
    {({ active }: { active: boolean }) => (
      <div
        className={cn(
          "relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none transition-colors",
          active ? "bg-accent text-accent-foreground" : "",
          className
        )}
        {...props}
      >
        <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
          <Circle className="h-2 w-2 fill-current" />
        </span>
        {children}
      </div>
    )}
  </Menu.Item>
)

const DropdownMenuLabel = ({
  inset,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { inset?: boolean }) => (
  <div
    className={cn("px-2 py-1.5 text-sm font-semibold", inset ? "pl-8" : "", className)}
    {...props}
  />
)

const DropdownMenuSeparator = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLHRElement>) => (
  <hr className={cn("-mx-1 my-1 h-px bg-muted", className)} {...props} />
)

const DropdownMenuShortcut = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) => (
  <span
    className={cn("ml-auto text-xs tracking-widest opacity-60", className)}
    {...props}
  />
)

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuGroup,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuRadioGroup,
}
