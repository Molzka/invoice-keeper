import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { WorkspaceArtKind } from './WorkspaceArt'
import { WorkspaceArt } from './WorkspaceArt'


interface PageHeaderProps {
  kind: WorkspaceArtKind
  title: string
  eyebrow: ReactNode
  description: string
  id?: string
  children?: ReactNode
}


export function PageHeader({ kind, title, eyebrow, description, id, children }: PageHeaderProps) {
  const headerRef = useRef<HTMLElement>(null)
  const introRef = useRef<HTMLDivElement>(null)
  const [copyEdge, setCopyEdge] = useState<number | null>(null)
  useEffect(() => {
    const measure = () => {
      const rect = introRef.current?.getBoundingClientRect()
      if (rect) setCopyEdge((rect.right + 24) / window.innerWidth * 1600)
    }
    const frame = requestAnimationFrame(measure)
    const observer = new ResizeObserver(measure)
    if (headerRef.current) observer.observe(headerRef.current)
    if (introRef.current) observer.observe(introRef.current)
    window.addEventListener('resize', measure)
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', measure) }
  }, [])
  return <header ref={headerRef} className="page-head page-heading" data-section={kind}>
    <div ref={introRef} className="page-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="page-title" id={id} tabIndex={-1}>{title}<span className="title-dot" aria-hidden="true">.</span></h1>
      <p className="page-subtitle">{description}</p>
    </div>
    <div className="page-heading-art"><WorkspaceArt key={kind} kind={kind} copyEdge={copyEdge} className="page-heading-visual" /></div>
    {children && <div className="page-heading-action">{children}</div>}
  </header>
}
