import * as React from "react"
import {
  Dialog as HeadlessDialog,
  DialogBackdrop,
  DialogPanel,
  DialogTitle as HeadlessDialogTitle,
  DialogDescription as HeadlessDialogDescription,
  Transition,
} from "@headlessui/react"
import { X } from "lucide-react"
import { Fragment } from "react"

import { cn } from "@/lib/utils"

const DialogContext = React.createContext<{
  onOpenChange: (open: boolean) => void
} | null>(null)

// Dialog — root component. Manages open/close state and renders the backdrop.
// Renders inline (no portal), so CSS custom properties cascade normally.
const Dialog = ({
  open,
  onOpenChange,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}) => (
  <Transition show={open} as={Fragment} appear>
    <HeadlessDialog open={open} onClose={onOpenChange}>
      <DialogContext.Provider value={{ onOpenChange }}>
        {/* Backdrop — wrapped in Transition.Child for fade animations */}
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <DialogBackdrop className="fixed inset-0 z-50 bg-black/80" />
        </Transition.Child>

        {/* Content — rendered inline inside #root, inherits CSS vars */}
        {children}
      </DialogContext.Provider>
    </HeadlessDialog>
  </Transition>
)

// DialogContent — the modal panel with enter/leave transitions.
const DialogContent = ({
  className,
  children,
}: {
  className?: string
  children?: React.ReactNode
}) => (
  <Transition.Child
    as={Fragment}
    enter="ease-out duration-200"
    enterFrom="opacity-0 scale-95"
    enterTo="opacity-100 scale-100"
    leave="ease-in duration-150"
    leaveFrom="opacity-100 scale-100"
    leaveTo="opacity-0 scale-95"
  >
    <DialogPanel
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg gap-4 border bg-background p-6 shadow-lg duration-200 sm:rounded-lg",
        className
      )}
      style={{ transform: "translate(-50%, -50%)" }}
    >
      {children}
      {/* Close button — uses context to close the dialog */}
      <CloseButton />
    </DialogPanel>
  </Transition.Child>
)

const CloseButton = () => {
  const ctx = React.useContext(DialogContext);
  return (
    <button
      type="button"
      className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none"
      onClick={() => ctx?.onOpenChange(false)}
    >
      <X className="h-4 w-4" />
      <span className="sr-only">Close</span>
    </button>
  );
}

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-1.5 text-center sm:text-left",
      className
    )}
    {...props}
  />
)
DialogHeader.displayName = "DialogHeader"

const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
      className
    )}
    {...props}
  />
)
DialogFooter.displayName = "DialogFooter"

const DialogTitle = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) => (
  <HeadlessDialogTitle
    className={cn(
      "text-lg font-semibold leading-none tracking-tight",
      className
    )}
    {...props}
  />
)
DialogTitle.displayName = "DialogTitle"

const DialogDescription = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) => (
  <HeadlessDialogDescription
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
)
DialogDescription.displayName = "DialogDescription"

// Stub components for backward API compatibility with existing imports
const DialogTrigger = ({ children }: { children: React.ReactNode }) => <>{children}</>
const DialogPortal = ({ children }: { children: React.ReactNode }) => <>{children}</>
const DialogOverlay = () => null
const DialogClose = ({
  children,
  onClick,
}: {
  children?: React.ReactNode
  onClick?: () => void
}) => (
  <button type="button" onClick={onClick}>
    {children}
  </button>
)

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogClose,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
}
