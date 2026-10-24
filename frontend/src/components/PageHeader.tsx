import type { ReactNode } from 'react'
import { WorkspaceArt } from './WorkspaceArt'


interface PageHeaderProps {
  kind: 'payments' | 'recurring' | 'history' | 'users'
  title: string
  eyebrow: ReactNode
  description: string
  id?: string
  children?: ReactNode
}


export function PageHeader({ kind, title, eyebrow, description, id, children }: PageHeaderProps) {
  return <header className="page-head page-heading" data-section={kind}>
    <div className="page-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="page-title" id={id} tabIndex={-1}>{title}<span className="title-dot" aria-hidden="true">.</span></h1>
      <p className="page-subtitle">{description}</p>
    </div>
    <WorkspaceArt key={kind} kind={kind} className="page-heading-visual" />
    {children && <div className="page-heading-action">{children}</div>}
  </header>
}
