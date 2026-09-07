import { useTheme } from "next-themes"
import { type FC } from "react"

export const ModeToggle: FC = () => {
  const { setTheme } = useTheme()

  return (
    <select
      onChange={e => setTheme(e.target.value)}
      className="h-8 rounded-md border border-input bg-background px-2 py-1 text-sm text-foreground cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      aria-label="Select theme"
      defaultValue="system"
    >
      <option value="light">Light</option>
      <option value="dark">Dark</option>
      <option value="system">System</option>
    </select>
  )
}
