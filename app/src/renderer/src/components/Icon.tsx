import {
  ListTodo,
  MessageSquare,
  Mail,
  MessageCircle,
  Phone,
  RefreshCw,
  Settings as SettingsIcon,
  Pin,
  Search,
  RotateCcw,
  Send,
  Folder,
  X,
  Paperclip,
  Menu,
  ArrowLeft,
} from 'lucide-react'

const REGISTRY = {
  tasks: ListTodo,
  chat: MessageSquare,
  mail: Mail,
  whatsapp: MessageCircle,
  phone: Phone,
  refresh: RefreshCw,
  settings: SettingsIcon,
  pin: Pin,
  search: Search,
  reopen: RotateCcw,
  send: Send,
  folder: Folder,
  close: X,
  attach: Paperclip,
  menu: Menu,
  back: ArrowLeft,
} as const

export type IconName = keyof typeof REGISTRY

interface IconProps {
  name: IconName
  size?: number
  className?: string
  'aria-label'?: string
}

export default function Icon({ name, size = 18, className, ...rest }: IconProps): JSX.Element {
  const Component = REGISTRY[name]
  return (
    <Component
      size={size}
      strokeWidth={1.5}
      className={className}
      aria-hidden={rest['aria-label'] ? undefined : true}
      {...rest}
    />
  )
}
