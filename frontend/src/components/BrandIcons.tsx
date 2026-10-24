import { forwardRef } from 'react'
import type { ForwardRefExoticComponent, RefAttributes, SVGProps } from 'react'
import type { Icon } from '@phosphor-icons/react'
import { ArrowDownIcon as PhosphorArrowDown } from '@phosphor-icons/react/dist/csr/ArrowDown'
import { ArrowLeftIcon as PhosphorArrowLeft } from '@phosphor-icons/react/dist/csr/ArrowLeft'
import { ArrowRightIcon as PhosphorArrowRight } from '@phosphor-icons/react/dist/csr/ArrowRight'
import { ArrowSquareOutIcon as PhosphorArrowSquareOut } from '@phosphor-icons/react/dist/csr/ArrowSquareOut'
import { ArrowUUpLeftIcon as PhosphorArrowUUpLeft } from '@phosphor-icons/react/dist/csr/ArrowUUpLeft'
import { ArrowUpIcon as PhosphorArrowUp } from '@phosphor-icons/react/dist/csr/ArrowUp'
import { ArrowUpRightIcon as PhosphorArrowUpRight } from '@phosphor-icons/react/dist/csr/ArrowUpRight'
import { ArrowsClockwiseIcon as PhosphorArrowsClockwise } from '@phosphor-icons/react/dist/csr/ArrowsClockwise'
import { CalendarCheckIcon as PhosphorCalendarCheck } from '@phosphor-icons/react/dist/csr/CalendarCheck'
import { CalendarDotsIcon as PhosphorCalendarDots } from '@phosphor-icons/react/dist/csr/CalendarDots'
import { CaretDownIcon as PhosphorCaretDown } from '@phosphor-icons/react/dist/csr/CaretDown'
import { CaretLeftIcon as PhosphorCaretLeft } from '@phosphor-icons/react/dist/csr/CaretLeft'
import { CaretRightIcon as PhosphorCaretRight } from '@phosphor-icons/react/dist/csr/CaretRight'
import { CaretUpIcon as PhosphorCaretUp } from '@phosphor-icons/react/dist/csr/CaretUp'
import { CheckIcon as PhosphorCheck } from '@phosphor-icons/react/dist/csr/Check'
import { CheckCircleIcon as PhosphorCheckCircle } from '@phosphor-icons/react/dist/csr/CheckCircle'
import { ClockIcon as PhosphorClock } from '@phosphor-icons/react/dist/csr/Clock'
import { ClockCounterClockwiseIcon as PhosphorClockCounterClockwise } from '@phosphor-icons/react/dist/csr/ClockCounterClockwise'
import { CoinsIcon as PhosphorCoins } from '@phosphor-icons/react/dist/csr/Coins'
import { DownloadSimpleIcon as PhosphorDownloadSimple } from '@phosphor-icons/react/dist/csr/DownloadSimple'
import { EyeIcon as PhosphorEye } from '@phosphor-icons/react/dist/csr/Eye'
import { EyeSlashIcon as PhosphorEyeSlash } from '@phosphor-icons/react/dist/csr/EyeSlash'
import { FileTextIcon as PhosphorFileText } from '@phosphor-icons/react/dist/csr/FileText'
import { InfoIcon as PhosphorInfo } from '@phosphor-icons/react/dist/csr/Info'
import { KeyIcon as PhosphorKey } from '@phosphor-icons/react/dist/csr/Key'
import { LinkIcon as PhosphorLink } from '@phosphor-icons/react/dist/csr/Link'
import { ListBulletsIcon as PhosphorListBullets } from '@phosphor-icons/react/dist/csr/ListBullets'
import { ListChecksIcon as PhosphorListChecks } from '@phosphor-icons/react/dist/csr/ListChecks'
import { MagnifyingGlassIcon as PhosphorMagnifyingGlass } from '@phosphor-icons/react/dist/csr/MagnifyingGlass'
import { PaperPlaneTiltIcon as PhosphorPaperPlaneTilt } from '@phosphor-icons/react/dist/csr/PaperPlaneTilt'
import { PaperclipIcon as PhosphorPaperclip } from '@phosphor-icons/react/dist/csr/Paperclip'
import { PlusIcon as PhosphorPlus } from '@phosphor-icons/react/dist/csr/Plus'
import { PlusCircleIcon as PhosphorPlusCircle } from '@phosphor-icons/react/dist/csr/PlusCircle'
import { ReceiptIcon as PhosphorReceipt } from '@phosphor-icons/react/dist/csr/Receipt'
import { RepeatIcon as PhosphorRepeat } from '@phosphor-icons/react/dist/csr/Repeat'
import { SignOutIcon as PhosphorSignOut } from '@phosphor-icons/react/dist/csr/SignOut'
import { SquareIcon as PhosphorSquare } from '@phosphor-icons/react/dist/csr/Square'
import { TrashIcon as PhosphorTrash } from '@phosphor-icons/react/dist/csr/Trash'
import { TrayIcon as PhosphorTray } from '@phosphor-icons/react/dist/csr/Tray'
import { UploadSimpleIcon as PhosphorUploadSimple } from '@phosphor-icons/react/dist/csr/UploadSimple'
import { UserIcon as PhosphorUser } from '@phosphor-icons/react/dist/csr/User'
import { UserMinusIcon as PhosphorUserMinus } from '@phosphor-icons/react/dist/csr/UserMinus'
import { UserPlusIcon as PhosphorUserPlus } from '@phosphor-icons/react/dist/csr/UserPlus'
import { WalletIcon as PhosphorWallet } from '@phosphor-icons/react/dist/csr/Wallet'
import { WarningCircleIcon as PhosphorWarningCircle } from '@phosphor-icons/react/dist/csr/WarningCircle'
import { SunIcon as PhosphorSun } from '@phosphor-icons/react/dist/csr/Sun'
import { MoonIcon as PhosphorMoon } from '@phosphor-icons/react/dist/csr/Moon'
import { DesktopIcon as PhosphorDesktop } from '@phosphor-icons/react/dist/csr/Desktop'
import { XIcon as PhosphorX } from '@phosphor-icons/react/dist/csr/X'

/** Filled, rounded icons used throughout the Aeza interface. */
export type BrandIconProps = SVGProps<SVGSVGElement> & {
  size?: number | string
  absoluteStrokeWidth?: boolean
}

// The alias keeps existing icon-typed component props compatible during migration.
export type LucideIcon = ForwardRefExoticComponent<BrandIconProps & RefAttributes<SVGSVGElement>>

function filledIcon(Component: Icon, name: string, weight: 'fill' | 'bold' = 'fill'): LucideIcon {
  const IconComponent = forwardRef<SVGSVGElement, BrandIconProps>(({ size = 24, className, strokeWidth, absoluteStrokeWidth, ...props }, ref) => {
    // Stroke-only options belonged to the previous outline set; solid paths keep
    // their geometry at every size. Existing callers may still provide them.
    void strokeWidth
    void absoluteStrokeWidth
    return <Component aria-hidden="true" focusable="false" {...props} ref={ref} size={size} weight={weight} className={`brand-icon lucide lucide-${name}${className ? ` ${className}` : ''}`} />
  })
  IconComponent.displayName = `BrandIcon(${name})`
  return IconComponent
}


/** Original guide silhouettes, shared with the section tiles. */
function guideIcon(name: string, file: string, viewBox: string): LucideIcon {
  const IconComponent = forwardRef<SVGSVGElement, BrandIconProps>(({ size = 24, className, strokeWidth, absoluteStrokeWidth, ...props }, ref) => {
    void strokeWidth
    void absoluteStrokeWidth
    return <svg aria-hidden="true" focusable="false" {...props} ref={ref} width={size} height={size} viewBox={viewBox} className={`brand-icon lucide lucide-${name}${className ? ` ${className}` : ''}`}><use href={`/brand/icons/${file}-glyph.svg#glyph`}/></svg>
  })
  IconComponent.displayName = `AezaGuideIcon(${name})`
  return IconComponent
}

export const AlertCircle = filledIcon(PhosphorWarningCircle, 'alert-circle')
export const ArrowRight = filledIcon(PhosphorArrowRight, 'arrow-right')
export const ArrowUpRight = filledIcon(PhosphorArrowUpRight, 'arrow-up-right')
export const CalendarClock = filledIcon(PhosphorCalendarCheck, 'calendar-clock')
export const CalendarDays = filledIcon(PhosphorCalendarDots, 'calendar-days')
export const Check = filledIcon(PhosphorCheck, 'check', 'bold')
export const ChevronDown = filledIcon(PhosphorCaretDown, 'chevron-down')
export const ChevronLeft = filledIcon(PhosphorCaretLeft, 'chevron-left')
export const ChevronRight = filledIcon(PhosphorCaretRight, 'chevron-right')
export const CirclePlus = filledIcon(PhosphorPlusCircle, 'circle-plus')
export const Clock3 = filledIcon(PhosphorClock, 'clock-3')
export const Coins = filledIcon(PhosphorCoins, 'coins')
export const Eye = filledIcon(PhosphorEye, 'eye')
export const EyeOff = filledIcon(PhosphorEyeSlash, 'eye-off')
export const FilePenLine = filledIcon(PhosphorFileText, 'file-pen-line')
export const History = filledIcon(PhosphorClockCounterClockwise, 'history')
export const Inbox = filledIcon(PhosphorTray, 'inbox')
export const Info = filledIcon(PhosphorInfo, 'info')
export const KeyRound = filledIcon(PhosphorKey, 'key-round')
export const LayoutList = filledIcon(PhosphorListBullets, 'layout-list')
export const ListChecks = filledIcon(PhosphorListChecks, 'list-checks')
export const LogOut = filledIcon(PhosphorSignOut, 'log-out')
export const PencilLine = guideIcon('pencil-line', 'note-pencil', '0 0 77.149 77.149')
export const Plus = filledIcon(PhosphorPlus, 'plus', 'bold')
export const ReceiptText = filledIcon(PhosphorReceipt, 'receipt-text')
export const RefreshCw = filledIcon(PhosphorArrowsClockwise, 'refresh-cw')
export const Repeat2 = filledIcon(PhosphorRepeat, 'repeat-2')
export const Search = filledIcon(PhosphorMagnifyingGlass, 'search')
export const Send = filledIcon(PhosphorPaperPlaneTilt, 'send')
export const ShieldCheck = guideIcon('shield-check', 'shield', '0 0 84.812 84.812')
export const SquarePen = guideIcon('square-pen', 'note-pencil', '0 0 77.149 77.149')
export const Undo2 = filledIcon(PhosphorArrowUUpLeft, 'undo-2')
export const UserMinus = filledIcon(PhosphorUserMinus, 'user-minus')
export const UserPlus = filledIcon(PhosphorUserPlus, 'user-plus')
export const UserRound = filledIcon(PhosphorUser, 'user-round')
export const Users = guideIcon('users', 'users', '0 0 103.568 103.568')
export const X = filledIcon(PhosphorX, 'x', 'bold')
export const Square = filledIcon(PhosphorSquare, 'square')
export const Trash2 = filledIcon(PhosphorTrash, 'trash-2')
export const Wallet = filledIcon(PhosphorWallet, 'wallet')
export const CreditCard = guideIcon('credit-card', 'credit-card', '0 0 98.224 98.224')
export const Link = filledIcon(PhosphorLink, 'link')
export const ExternalLink = filledIcon(PhosphorArrowSquareOut, 'external-link')
export const Download = filledIcon(PhosphorDownloadSimple, 'download')
export const Upload = filledIcon(PhosphorUploadSimple, 'upload')
export const FileText = filledIcon(PhosphorFileText, 'file-text')
export const Paperclip = filledIcon(PhosphorPaperclip, 'paperclip')
export const BarChart3 = guideIcon('bar-chart-3', 'chart', '0 0 72.945 72.945')
export const ChevronUp = filledIcon(PhosphorCaretUp, 'chevron-up')
export const ArrowLeft = filledIcon(PhosphorArrowLeft, 'arrow-left')
export const ArrowDown = filledIcon(PhosphorArrowDown, 'arrow-down')
export const ArrowUp = filledIcon(PhosphorArrowUp, 'arrow-up')
export const CheckCircle2 = filledIcon(PhosphorCheckCircle, 'check-circle-2')
export const CircleAlert = filledIcon(PhosphorWarningCircle, 'circle-alert')
export const CircleCheck = filledIcon(PhosphorCheckCircle, 'circle-check')

export const Sun = filledIcon(PhosphorSun, 'sun')
export const Moon = filledIcon(PhosphorMoon, 'moon')
export const Monitor = filledIcon(PhosphorDesktop, 'monitor')
